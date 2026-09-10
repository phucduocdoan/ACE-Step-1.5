"""Batch runner for the legacy ACE-Step async music API."""

from __future__ import annotations

import argparse
import hashlib
import json
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
BATCH_ONLY_FIELDS = frozenset({"jobs", "max_inflight", "manifest", "no_resume"})


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
    parser.set_defaults(timeout=1800.0)
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

    allowed = set(vars(defaults)) - BATCH_ONLY_FIELDS
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
        job_id = explicit_id or auto_job_id(overrides, seen)
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
    with manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


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

    def record(job: Job, row: dict[str, Any]) -> None:
        append_manifest_row(manifest_path, {"id": job.job_id, "prompt": job.args.prompt, **row})

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

            for item in items:
                task_id = str(item.get("task_id", ""))
                job = inflight.get(task_id)
                if job is None:
                    continue
                status = int(item.get("status", 0))
                if status == 0:
                    continue

                del inflight[task_id]
                last_completion = monotonic()
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
            for task_id, job in inflight.items():
                failed += 1
                record(job, {"task_id": task_id, "status": "failed", "error": "batch stalled"})
            for job in pending:
                failed += 1
                record(job, {"status": "failed", "error": "batch stalled before submission"})
            print(f"[stalled] no job completed within {args.timeout}s, aborting batch")
            break

        if (pending or inflight) and not progressed:
            sleep(args.poll_interval)

    return succeeded, failed


def main(argv: Optional[list[str]] = None) -> int:
    """Run the batch client from the command line."""

    parser = build_batch_arg_parser()
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest) if args.manifest else Path(args.output_dir) / "manifest.jsonl"

    try:
        if args.max_inflight < 1:
            raise ValueError("--max-inflight must be >= 1")
        jobs = load_jobs(args.jobs, args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    if not args.no_resume:
        completed = load_completed_job_ids(manifest_path)
        remaining = [job for job in jobs if job.job_id not in completed]
        if len(remaining) != len(jobs):
            print(f"resume: skipping {len(jobs) - len(remaining)} job(s) already succeeded")
        jobs = remaining

    if not jobs:
        print("nothing to do")
        return 0

    print(f"running {len(jobs)} job(s), max inflight {args.max_inflight}, manifest {manifest_path}")
    with requests.Session() as session:
        # GET /v1/audio is auth-gated too, and download_audio_files does not
        # build per-request headers, so authenticate the session itself.
        session.headers.update(build_headers(args.api_key))
        succeeded, failed = run_batch(session, args, jobs, manifest_path)

    print(f"done: succeeded={succeeded} failed={failed} total={succeeded + failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
