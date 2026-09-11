"""Batch runner for the legacy ACE-Step async music API."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from acestep.api_client import (
    build_arg_parser,
    build_headers,
    build_release_task_payload,
    download_audio_files,
    parse_query_result_item,
    query_tasks,
    submit_generation_task,
    validate_args,
)


# CLI flags that configure the batch runner itself and cannot be set per job.
BATCH_ONLY_FIELDS = frozenset({"jobs", "max_inflight", "manifest", "no_resume", "concat"})

# Single-job flags that run_batch reads from the global args instead of the
# per-job args, so a per-job override would silently be ignored.
CLI_ONLY_FIELDS = frozenset(
    {"base_url", "api_key", "output_dir", "timeout", "poll_interval", "no_download"}
)


@dataclass
class Job:
    """One batch entry: a job ID plus its fully resolved arguments."""

    job_id: str
    args: argparse.Namespace


def build_batch_arg_parser() -> argparse.ArgumentParser:
    """Build the batch parser: the single-job flags plus batch controls."""

    parser = build_arg_parser()
    parser.description = "Run a batch of ACE-Step generation jobs from a JSONL file."
    parser.epilog = (
        "Every non-batch flag is the default for jobs that do not override it. "
        "In batch mode --timeout is a stall timeout: the batch aborts when no job "
        "at all completes within that many seconds (a single job's own wait can be "
        "much longer, because the server generates queued jobs one at a time)."
    )
    parser.add_argument("--jobs", required=True, help="JSONL file with one job object per line.")
    parser.add_argument(
        "--max-inflight",
        type=int,
        default=8,
        help="Maximum tasks submitted but not yet finished.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Manifest path. Defaults to <output-dir>/manifest.jsonl",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Re-run jobs already recorded as succeeded in the manifest.",
    )
    parser.add_argument(
        "--concat",
        default=None,
        help=(
            "After the batch, join every succeeded job's audio into this one file "
            "with ffmpeg, in jobs-file order. Needs ffmpeg on PATH."
        ),
    )
    parser.set_defaults(timeout=1800.0)
    # --timeout means something different here than for a single job. argparse
    # offers no public way to re-word an inherited option, and re-adding it
    # needs the equally private parser._optionals.conflict_handler.
    parser._option_string_actions["--timeout"].help = (
        "Stall timeout: give up when no job at all completes within this many seconds."
    )
    return parser


def auto_job_id(overrides: dict[str, Any], taken: set[str]) -> str:
    """Derive a job ID from the entry's own fields when it declares no ``id``.

    Resume matches on the job ID, so a positional ID (``job-0003``) would rebind
    to a different line as soon as the jobs file is edited, silently skipping a
    job that never ran. Hashing the entry keeps the ID attached to its content.
    """

    canonical = json.dumps(overrides, sort_keys=True, ensure_ascii=False)
    base = f"job-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:8]}"
    if base not in taken:
        return base
    # Byte-identical job lines are legitimate; number them deterministically.
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def load_jobs(jobs_path: str, defaults: argparse.Namespace) -> list[Job]:
    """Read a JSONL job file, layering each entry over the CLI defaults."""

    allowed = set(vars(defaults)) - BATCH_ONLY_FIELDS - CLI_ONLY_FIELDS
    jobs: list[Job] = []
    seen: set[str] = set()
    lines = Path(jobs_path).read_text(encoding="utf-8").splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{jobs_path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(entry, dict):
            raise ValueError(f"{jobs_path}:{line_number}: each job line must be a JSON object")

        overrides = dict(entry)
        explicit_id = str(overrides.pop("id", "") or "").strip()
        if explicit_id and explicit_id in seen:
            raise ValueError(f"{jobs_path}:{line_number}: duplicate job id '{explicit_id}'")
        if "/" in explicit_id or "\\" in explicit_id:
            raise ValueError(
                f"{jobs_path}:{line_number}: job id must not contain a path separator: '{explicit_id}'"
            )
        job_id = explicit_id or auto_job_id(overrides, seen)

        cli_only = sorted(set(overrides) & CLI_ONLY_FIELDS)
        if cli_only:
            raise ValueError(
                f"{jobs_path}:{line_number}: field(s) can only be set on the command line, "
                f"not per job: {', '.join(cli_only)}"
            )
        unknown = sorted(set(overrides) - allowed)
        if unknown:
            raise ValueError(
                f"{jobs_path}:{line_number}: unknown job field(s): {', '.join(unknown)}"
            )

        seen.add(job_id)
        jobs.append(Job(job_id=job_id, args=argparse.Namespace(**{**vars(defaults), **overrides})))
    return jobs


def load_completed_job_ids(manifest_path: Path) -> set[str]:
    """Return job IDs recorded as succeeded in an existing manifest."""

    if not manifest_path.exists():
        return set()
    completed: set[str] = set()
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("status") == "succeeded" and row.get("id"):
            completed.add(str(row["id"]))
    return completed


def append_manifest_row(manifest_path: Path, row: dict[str, Any]) -> None:
    """Append one manifest row, flushing immediately so runs stay resumable."""

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # A crash mid-write can leave the file without a trailing newline; without
    # this, the next append would concatenate onto that torn row and corrupt
    # this genuinely complete one too.
    needs_leading_newline = False
    if manifest_path.exists() and manifest_path.stat().st_size > 0:
        with manifest_path.open("rb") as handle:
            handle.seek(-1, 2)
            needs_leading_newline = handle.read(1) != b"\n"
    with manifest_path.open("a", encoding="utf-8") as handle:
        if needs_leading_newline:
            handle.write("\n")
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def ordered_manifest_files(jobs: list[Job], manifest_path: Path) -> list[Path]:
    """Return every succeeded job's audio files, in jobs-file order.

    The order comes from the jobs file, not the manifest, so a resumed run
    produces the same sequence as an uninterrupted one: the manifest is in
    completion order, and resume appends the leftovers after rows that already
    succeeded.
    """

    by_job: dict[str, list[str]] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("status") == "succeeded" and row.get("id"):
                # --no-resume appends a second row for a job that already had
                # one, so the newest row wins rather than the first.
                by_job[str(row["id"])] = [str(name) for name in row.get("files") or []]

    files: list[Path] = []
    for job in jobs:
        recorded = by_job.get(job.job_id)
        if not recorded:
            print(f"[concat] skipping {job.job_id}: nothing recorded as succeeded")
            continue
        for name in recorded:
            path = Path(name)
            if not path.exists():
                print(f"[concat] skipping {name}: file is gone")
                continue
            files.append(path)
    return files


def concat_audio_files(files: list[Path], output_path: Path) -> None:
    """Join audio files into ``output_path`` with ffmpeg."""

    if not files:
        raise RuntimeError("nothing to concatenate: no succeeded audio on disk")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("--concat needs ffmpeg on PATH")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    list_path: Optional[Path] = None
    if {path.suffix.lower() for path in files} == {suffix}:
        # Same format in and out, so the concat demuxer can copy the streams.
        # The server already returns lossy mp3; re-encoding that would add a
        # second generation of loss for nothing.
        #
        # The list format quotes paths with single quotes, so a literal one has
        # to be closed, escaped and reopened.
        listing = "".join(
            "file '{}'\n".format(str(path.resolve()).replace("'", "'\\''")) for path in files
        )
        list_path = output_path.parent / f".{output_path.name}.concat.txt"
        list_path.write_text(listing, encoding="utf-8")
        inputs = ["-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy"]
    else:
        # The demuxer decodes every input with the first one's codec, so on
        # mixed formats it drops whole tracks while still exiting 0. The concat
        # filter opens each input separately, so it actually joins them; if
        # their sample rates disagree it fails loudly instead of losing audio.
        inputs = []
        for path in files:
            inputs += ["-i", str(path)]
        streams = "".join(f"[{index}:a]" for index in range(len(files)))
        inputs += [
            "-filter_complex", f"{streams}concat=n={len(files)}:v=0:a=1[out]",
            "-map", "[out]",
        ]
        if suffix == ".mp3":
            # ffmpeg defaults mp3 to 128k, which is audibly lossy on music.
            inputs += ["-c:a", "libmp3lame", "-q:a", "2"]
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                *inputs,
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )
    finally:
        if list_path is not None:
            list_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip() or result.returncode}")


def _is_queue_full_error(exc: requests.HTTPError) -> bool:
    """Report whether the server rejected a submission because its queue is full."""

    return exc.response is not None and exc.response.status_code == 429


def _collect_job_files(
    session: requests.Session,
    args: argparse.Namespace,
    job: Job,
    audio_items: list[dict[str, Any]],
) -> list[str]:
    """Download a finished job's audio, or list its URLs when downloads are off."""

    if args.no_download:
        return [str(item["file"]) for item in audio_items if str(item.get("file", "")).strip()]
    saved = download_audio_files(
        session=session,
        base_url=args.base_url,
        audio_items=audio_items,
        output_dir=args.output_dir,
        file_prefix=job.job_id,
    )
    return [str(path) for path in saved]


# Consecutive stall windows with no successful completion before the whole
# batch gives up, rather than just the currently in-flight job(s).
MAX_CONSECUTIVE_STALLS = 3


def run_batch(
    session: requests.Session,
    args: argparse.Namespace,
    jobs: list[Job],
    manifest_path: Path,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[int, int]:
    """Run every job through the API queue, returning ``(succeeded, failed)``."""

    pending: deque[Job] = deque(jobs)
    inflight: dict[str, Job] = {}
    succeeded = 0
    failed = 0
    last_completion = monotonic()
    consecutive_stalls = 0

    def record(job: Job, row: dict[str, Any]) -> None:
        append_manifest_row(manifest_path, {"id": job.job_id, "prompt": job.args.prompt, **row})

    try:
        while pending or inflight:
            # Set whenever a job reaches a terminal state this cycle. A completion
            # frees the server's worker, so the next job must be submitted at once
            # instead of after another poll interval of idle GPU.
            progressed = False

            while pending and len(inflight) < args.max_inflight:
                job = pending[0]
                try:
                    validate_args(job.args)
                except ValueError as exc:
                    pending.popleft()
                    failed += 1
                    record(job, {"status": "failed", "error": f"invalid job: {exc}"})
                    print(f"[invalid] {job.job_id}: {exc}")
                    continue

                try:
                    task_id = submit_generation_task(
                        session=session,
                        base_url=args.base_url,
                        api_key=args.api_key,
                        payload=build_release_task_payload(job.args),
                        src_audio=job.args.src_audio,
                        reference_audio=job.args.reference_audio,
                    )
                except requests.HTTPError as exc:
                    if _is_queue_full_error(exc):
                        break
                    pending.popleft()
                    failed += 1
                    record(job, {"status": "failed", "error": f"submit failed: {exc}"})
                    print(f"[failed] {job.job_id}: submit failed: {exc}")
                    continue
                except (requests.ConnectionError, requests.Timeout) as exc:
                    print(f"[warn] {job.job_id}: submit unreachable, retrying: {exc}")
                    break
                except Exception as exc:
                    pending.popleft()
                    failed += 1
                    record(job, {"status": "failed", "error": f"submit failed: {exc}"})
                    print(f"[failed] {job.job_id}: submit failed: {exc}")
                    continue

                pending.popleft()
                if task_id in inflight:
                    # Unreachable against this server (task ids are uuid4), but a
                    # reused task_id would otherwise silently overwrite the entry
                    # and lose the earlier job with no manifest row.
                    displaced = inflight[task_id]
                    failed += 1
                    record(
                        displaced,
                        {
                            "task_id": task_id,
                            "status": "failed",
                            "error": f"task_id '{task_id}' was reused by another submission",
                        },
                    )
                    print(f"[warn] {displaced.job_id}: task_id '{task_id}' reused by {job.job_id}, displaced job failed")
                inflight[task_id] = job
                print(f"[submit] {job.job_id} -> {task_id} (inflight {len(inflight)}, pending {len(pending)})")

            if inflight:
                try:
                    items = query_tasks(session, args.base_url, args.api_key, list(inflight))
                except requests.RequestException as exc:
                    # A dropped connection is routine while the server is busy loading
                    # models; the stall timeout below bounds how long we keep retrying.
                    print(f"[warn] poll failed, retrying: {exc}")
                    items = []

                if not isinstance(items, list):
                    print(f"[warn] poll returned a malformed response, retrying: {items!r}")
                    items = []

                for item in items:
                    if not isinstance(item, dict):
                        print(f"[warn] poll returned a malformed item, skipping: {item!r}")
                        continue
                    task_id = str(item.get("task_id", ""))
                    job = inflight.get(task_id)
                    if job is None:
                        continue
                    status = int(item.get("status", 0))
                    if status == 0:
                        continue

                    del inflight[task_id]
                    last_completion = monotonic()
                    # A terminal result of any kind proves the server is alive,
                    # so it clears the stall streak as much as a success does.
                    consecutive_stalls = 0
                    progressed = True
                    if status != 1:
                        # Anything that is neither pending (0) nor success (1) is a
                        # failure, including statuses this client does not know yet.
                        failed += 1
                        record(job, {"task_id": task_id, "status": "failed", "error": f"task failed: {item}"})
                        print(f"[failed] {job.job_id}: task failed (status {status})")
                        continue

                    try:
                        files = _collect_job_files(session, args, job, parse_query_result_item(item))
                    except Exception as exc:
                        failed += 1
                        record(job, {"task_id": task_id, "status": "failed", "error": f"download failed: {exc}"})
                        print(f"[failed] {job.job_id}: download failed: {exc}")
                        continue

                    if not files:
                        # The server reports success with a placeholder empty result
                        # when it produced no audio. Recording that as succeeded
                        # would make resume skip the job forever.
                        failed += 1
                        record(
                            job,
                            {
                                "task_id": task_id,
                                "status": "failed",
                                "error": "task succeeded but returned no audio",
                            },
                        )
                        print(f"[failed] {job.job_id}: task returned no audio")
                        continue

                    succeeded += 1
                    record(job, {"task_id": task_id, "status": "succeeded", "files": files})
                    print(f"[done] {job.job_id}: {len(files)} file(s)")

            if monotonic() - last_completion > args.timeout:
                consecutive_stalls += 1
                stalled = len(inflight)
                for task_id, job in inflight.items():
                    failed += 1
                    record(job, {"task_id": task_id, "status": "failed", "error": "batch stalled"})
                inflight.clear()

                if consecutive_stalls >= MAX_CONSECUTIVE_STALLS:
                    for job in pending:
                        failed += 1
                        record(job, {"status": "failed", "error": "batch stalled before submission"})
                    print(
                        f"[stalled] no job completed within {args.timeout}s "
                        f"({consecutive_stalls} consecutive stalls), aborting the rest of the batch"
                    )
                    break

                print(
                    f"[stalled] no job completed within {args.timeout}s "
                    f"({consecutive_stalls}/{MAX_CONSECUTIVE_STALLS} consecutive stalls), "
                    f"failed {stalled} in-flight job(s), continuing with the rest"
                )
                last_completion = monotonic()

            if (pending or inflight) and not progressed:
                sleep(args.poll_interval)
    except KeyboardInterrupt:
        print(
            f"[interrupted] succeeded={succeeded} failed={failed} "
            f"pending={len(pending)} inflight={len(inflight)}"
        )
        raise

    return succeeded, failed


def main(argv: Optional[list[str]] = None) -> int:
    """Run the batch client from the command line."""

    parser = build_batch_arg_parser()
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest) if args.manifest else Path(args.output_dir) / "manifest.jsonl"

    try:
        if args.max_inflight < 1:
            raise ValueError("--max-inflight must be >= 1")
        if args.concat and args.no_download:
            raise ValueError("--concat needs the audio on disk, so it cannot be used with --no-download")
        jobs = load_jobs(args.jobs, args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    # --concat orders by the jobs file, so it needs the full list, including the
    # jobs resume is about to drop: their audio belongs in the album too.
    all_jobs = jobs

    if not args.no_resume:
        completed = load_completed_job_ids(manifest_path)
        remaining = [job for job in jobs if job.job_id not in completed]
        if len(remaining) != len(jobs):
            print(f"resume: skipping {len(jobs) - len(remaining)} job(s) already succeeded")
        jobs = remaining

    failed = 0
    if not jobs:
        print("nothing to do")
        if not args.concat:
            return 0
    else:
        print(f"running {len(jobs)} job(s), max inflight {args.max_inflight}, manifest {manifest_path}")
        with requests.Session() as session:
            # GET /v1/audio is auth-gated too, and download_audio_files does not
            # build per-request headers, so authenticate the session itself.
            session.headers.update(build_headers(args.api_key))
            try:
                succeeded, failed = run_batch(session, args, jobs, manifest_path)
            except KeyboardInterrupt:
                return 130
            except Exception as exc:
                print(f"error: {exc}")
                return 1

        print(f"done: succeeded={succeeded} failed={failed} total={succeeded + failed}")

    if args.concat:
        output_path = Path(args.concat)
        try:
            concat_audio_files(ordered_manifest_files(all_jobs, manifest_path), output_path)
        except (OSError, RuntimeError) as exc:
            print(f"error: {exc}")
            return 1
        print(f"[concat] wrote {output_path}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
