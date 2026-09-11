"""Tests for the ACE-Step async API batch runner."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import requests

from acestep.api_batch import (
    append_manifest_row,
    build_batch_arg_parser,
    concat_audio_files,
    load_completed_job_ids,
    load_jobs,
    main,
    ordered_manifest_files,
    run_batch,
)


class FakeResponse:
    """Minimal stand-in for a ``requests`` response object."""

    def __init__(self, payload=None, status_code: int = 200, content: bytes = b"") -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        """Raise for error status codes the way ``requests`` does."""

        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        """Return the canned JSON payload."""

        return self._payload


class FakeApi:
    """In-memory stand-in for ``/release_task``, ``/query_result`` and audio downloads."""

    def __init__(
        self,
        polls_before_done: int = 1,
        fail_task_ids=(),
        submit_status_codes=(),
        submit_connection_errors: int = 0,
        poll_connection_errors: int = 0,
        empty_result_task_ids=(),
        unknown_status_task_ids=(),
        stalled_task_ids=(),
        malformed_poll_responses=(),
    ) -> None:
        self.polls_before_done = polls_before_done
        self.fail_task_ids = set(fail_task_ids)
        self.submit_status_codes = deque(submit_status_codes)
        self.submit_connection_errors = submit_connection_errors
        self.poll_connection_errors = poll_connection_errors
        self.empty_result_task_ids = set(empty_result_task_ids)
        self.unknown_status_task_ids = set(unknown_status_task_ids)
        # Tasks that never leave status 0, e.g. a task_id the server forgot
        # about after a restart.
        self.stalled_task_ids = set(stalled_task_ids)
        # Canned malformed ``data`` payloads (a dict, or a list with a
        # non-dict item) returned in order before falling back to normal.
        self.malformed_poll_responses = deque(malformed_poll_responses)
        self.headers: dict[str, str] = {}
        self.submitted: list[str] = []
        self.polls: dict[str, int] = {}
        self.inflight = 0
        self.max_inflight_seen = 0
        self.download_count = 0

    def __enter__(self) -> "FakeApi":
        """Support the ``with requests.Session()`` idiom."""

        return self

    def __exit__(self, *exc_info) -> None:
        """Support the ``with requests.Session()`` idiom."""

        return None

    def post(self, url: str, **kwargs) -> FakeResponse:
        """Route a POST to the fake release-task or query-result handler."""

        if url.endswith("/release_task"):
            return self._release_task()
        if url.endswith("/query_result"):
            return self._query_result(kwargs["json"]["task_id_list"])
        raise AssertionError(f"unexpected POST to {url}")

    def get(self, url: str, **kwargs) -> FakeResponse:
        """Serve a fake audio download."""

        self.download_count += 1
        return FakeResponse(content=b"audio-bytes")

    def _release_task(self) -> FakeResponse:
        """Queue one task, honouring any scripted error status codes."""

        if self.submit_connection_errors:
            self.submit_connection_errors -= 1
            raise requests.ConnectionError("connection reset by peer")
        if self.submit_status_codes:
            status_code = self.submit_status_codes.popleft()
            if status_code >= 400:
                return FakeResponse(status_code=status_code)
        task_id = f"task-{len(self.submitted) + 1}"
        self.submitted.append(task_id)
        self.polls[task_id] = 0
        self.inflight += 1
        self.max_inflight_seen = max(self.max_inflight_seen, self.inflight)
        return FakeResponse({"data": {"task_id": task_id, "status": "queued"}})

    def _query_result(self, task_ids: list[str]) -> FakeResponse:
        """Report one item per queried task, finishing after enough polls."""

        if self.poll_connection_errors:
            self.poll_connection_errors -= 1
            raise requests.ConnectionError("connection reset by peer")
        if self.malformed_poll_responses:
            return FakeResponse({"data": self.malformed_poll_responses.popleft()})
        items = []
        for task_id in task_ids:
            if task_id in self.stalled_task_ids:
                items.append({"task_id": task_id, "status": 0, "result": "[]"})
                continue
            self.polls[task_id] = self.polls.get(task_id, 0) + 1
            if self.polls[task_id] < self.polls_before_done:
                items.append({"task_id": task_id, "status": 0, "result": "[]"})
                continue
            self.inflight -= 1
            if task_id in self.fail_task_ids:
                items.append({"task_id": task_id, "status": 2, "result": "[]"})
                continue
            if task_id in self.unknown_status_task_ids:
                items.append({"task_id": task_id, "status": 3, "result": "[]"})
                continue
            if task_id in self.empty_result_task_ids:
                # What the server really sends when it succeeds with no audio.
                placeholder = json.dumps([{"file": "", "wave": "", "status": 1}])
                items.append({"task_id": task_id, "status": 1, "result": placeholder})
                continue
            result = json.dumps([{"file": f"/v1/audio?path=%2Ftmp%2F{task_id}.mp3", "status": 1}])
            items.append({"task_id": task_id, "status": 1, "result": result})
        return FakeResponse({"data": items})


class DuplicateTaskIdApi(FakeApi):
    """Always returns the same task_id, to exercise the reused-task_id guard."""

    def _release_task(self) -> FakeResponse:
        """Queue a task under a fixed task_id, unlike the base class's unique IDs."""

        self.submitted.append("task-dup")
        self.polls["task-dup"] = 0
        return FakeResponse({"data": {"task_id": "task-dup", "status": "queued"}})


def build_args(jobs_path: str, output_dir: str, **overrides):
    """Build a batch argument namespace with test-friendly defaults."""

    argv = [
        "--jobs", jobs_path,
        "--output-dir", output_dir,
        # Must be positive: --poll-interval is validated. Sleep is injected in
        # tests, so this tiny interval keeps them fast without disabling it.
        "--poll-interval", "0.001",
    ]
    for key, value in overrides.items():
        argv.extend([f"--{key.replace('_', '-')}", str(value)])
    return build_batch_arg_parser().parse_args(argv)


def write_jobs_file(directory: str, lines: list[str]) -> str:
    """Write a JSONL jobs file and return its path."""

    path = Path(directory) / "jobs.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def read_manifest(manifest_path: Path) -> list[dict]:
    """Read every manifest row written during a run."""

    return [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ArgParserTests(unittest.TestCase):
    """The batch parser's help text must describe batch-mode semantics."""

    def test_timeout_help_describes_the_batch_wide_stall_meaning(self) -> None:
        """--timeout means a per-poll timeout in the single-job client, but a stall
        timeout here; the help text must say so instead of reusing that wording."""

        parser = build_batch_arg_parser()
        help_text = parser._option_string_actions["--timeout"].help
        self.assertIn("stall", help_text.lower())


class LoadJobsTests(unittest.TestCase):
    """Validate parsing of the JSONL job file."""

    def test_overrides_layer_over_cli_defaults(self) -> None:
        """Job fields should override CLI defaults and leave the rest intact."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, [
                "# a comment",
                "",
                '{"id": "song-01", "prompt": "lofi", "audio_duration": 45}',
                '{"prompt": "bolero"}',
            ])
            args = build_args(jobs_path, tmp, inference_steps=12)
            jobs = load_jobs(jobs_path, args)

        self.assertEqual("song-01", jobs[0].job_id)
        self.assertTrue(jobs[1].job_id.startswith("job-"))
        self.assertEqual("lofi", jobs[0].args.prompt)
        self.assertEqual(45, jobs[0].args.audio_duration)
        self.assertEqual(12, jobs[0].args.inference_steps)
        self.assertEqual(12, jobs[1].args.inference_steps)
        self.assertIsNone(jobs[1].args.audio_duration)

    def test_auto_ids_survive_editing_the_jobs_file(self) -> None:
        """An auto ID must follow its job line, not the line's position."""

        with tempfile.TemporaryDirectory() as tmp:
            before = write_jobs_file(tmp, [
                '{"prompt": "lofi"}',
                '{"prompt": "bolero"}',
            ])
            first = load_jobs(before, build_args(before, tmp))
            after = write_jobs_file(tmp, ['{"prompt": "bolero"}'])
            second = load_jobs(after, build_args(after, tmp))

        self.assertEqual(first[1].job_id, second[0].job_id)
        self.assertNotEqual(first[0].job_id, first[1].job_id)

    def test_identical_job_lines_get_distinct_ids(self) -> None:
        """Duplicate lines are legitimate and must not collide."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, [
                '{"prompt": "lofi"}',
                '{"prompt": "lofi"}',
            ])
            jobs = load_jobs(jobs_path, build_args(jobs_path, tmp))

        self.assertEqual(2, len(set(job.job_id for job in jobs)))

    def test_invalid_json_reports_line_number(self) -> None:
        """A malformed line should name the file and line number."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"prompt": "ok"}', '{"prompt": '])
            args = build_args(jobs_path, tmp)
            with self.assertRaisesRegex(ValueError, r"jobs\.jsonl:2: invalid JSON"):
                load_jobs(jobs_path, args)

    def test_unknown_field_is_rejected(self) -> None:
        """A misspelled job field should fail loudly instead of being ignored."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"prompt": "ok", "duration": 30}'])
            args = build_args(jobs_path, tmp)
            with self.assertRaisesRegex(ValueError, "unknown job field\\(s\\): duration"):
                load_jobs(jobs_path, args)

    def test_batch_only_field_is_not_a_valid_override(self) -> None:
        """Runner-level flags must not be settable per job."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"prompt": "ok", "max_inflight": 4}'])
            args = build_args(jobs_path, tmp)
            with self.assertRaisesRegex(ValueError, "unknown job field\\(s\\): max_inflight"):
                load_jobs(jobs_path, args)

    def test_cli_only_field_is_rejected_with_a_distinct_message(self) -> None:
        """A field run_batch reads from the global args must not be silently ignored per job."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"prompt": "ok", "output_dir": "elsewhere"}'])
            args = build_args(jobs_path, tmp)
            with self.assertRaisesRegex(
                ValueError,
                r"jobs\.jsonl:1: field\(s\) can only be set on the command line, not per job: output_dir",
            ):
                load_jobs(jobs_path, args)

    def test_job_id_with_path_separator_is_rejected(self) -> None:
        """A job id becomes a filename prefix and a manifest key, so it must not be a path."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "../escaped", "prompt": "ok"}'])
            args = build_args(jobs_path, tmp)
            with self.assertRaisesRegex(ValueError, "job id must not contain a path separator"):
                load_jobs(jobs_path, args)

    def test_duplicate_job_id_is_rejected(self) -> None:
        """Duplicate IDs would collide in output filenames, so reject them."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "a"}', '{"id": "a"}'])
            args = build_args(jobs_path, tmp)
            with self.assertRaisesRegex(ValueError, "duplicate job id 'a'"):
                load_jobs(jobs_path, args)


class ResumeTests(unittest.TestCase):
    """Validate manifest-driven resume support."""

    def test_only_succeeded_rows_count_as_completed(self) -> None:
        """Failed and malformed rows must not be skipped on a resumed run."""

        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.jsonl"
            manifest.write_text(
                '{"id": "a", "status": "succeeded"}\n'
                '{"id": "b", "status": "failed"}\n'
                "not json\n"
                "\n",
                encoding="utf-8",
            )
            self.assertEqual({"a"}, load_completed_job_ids(manifest))

    def test_missing_manifest_completes_nothing(self) -> None:
        """A first run has no manifest and must skip nothing."""

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(set(), load_completed_job_ids(Path(tmp) / "manifest.jsonl"))


class AppendManifestRowTests(unittest.TestCase):
    """A torn write must not corrupt the row appended after it."""

    def test_append_repairs_a_torn_previous_row(self) -> None:
        """A crash mid-write leaves no trailing newline; the next append must add one."""

        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.jsonl"
            manifest.write_text('{"id": "j1", "status": "succ', encoding="utf-8")
            append_manifest_row(manifest, {"id": "j2", "status": "succeeded"})

            self.assertIn("j2", load_completed_job_ids(manifest))


class RunBatchTests(unittest.TestCase):
    """Exercise the submit/poll/download scheduler."""

    def test_all_jobs_complete_and_files_use_job_ids(self) -> None:
        """Every job should download to a file named after its job ID."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, [
                '{"id": "song-01", "prompt": "a"}',
                '{"id": "song-02", "prompt": "b"}',
            ])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"
            api = FakeApi(polls_before_done=2)

            succeeded, failed = run_batch(api, args, jobs, manifest, sleep=lambda _: None)
            rows = read_manifest(manifest)

        self.assertEqual((2, 0), (succeeded, failed))
        self.assertEqual(2, api.download_count)
        self.assertEqual({"song-01", "song-02"}, {row["id"] for row in rows})
        self.assertTrue(all(row["status"] == "succeeded" for row in rows))
        by_id = {row["id"]: row for row in rows}
        self.assertTrue(by_id["song-01"]["files"][0].endswith("song-01_0.mp3"))
        self.assertEqual("a", by_id["song-01"]["prompt"])

    def test_max_inflight_is_never_exceeded(self) -> None:
        """The scheduler must keep the server queue within the configured window."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, [json.dumps({"id": f"j{i}"}) for i in range(5)])
            args = build_args(jobs_path, tmp, max_inflight=2)
            jobs = load_jobs(jobs_path, args)
            api = FakeApi(polls_before_done=3)

            succeeded, failed = run_batch(api, args, jobs, Path(tmp) / "manifest.jsonl", sleep=lambda _: None)

        self.assertEqual((5, 0), (succeeded, failed))
        self.assertEqual(5, len(api.submitted))
        self.assertEqual(2, api.max_inflight_seen)

    def test_invalid_job_does_not_abort_the_batch(self) -> None:
        """A job failing validation is recorded, and the rest still run."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, [
                '{"id": "bad", "task_type": "cover"}',
                '{"id": "good", "prompt": "a"}',
            ])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(FakeApi(), args, jobs, manifest, sleep=lambda _: None)
            by_id = {row["id"]: row for row in read_manifest(manifest)}

        self.assertEqual((1, 1), (succeeded, failed))
        self.assertIn("--src-audio is required", by_id["bad"]["error"])
        self.assertEqual("succeeded", by_id["good"]["status"])

    def test_failed_task_is_recorded_and_batch_continues(self) -> None:
        """A server-side task failure must not stop the remaining jobs."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}', '{"id": "j2"}'])
            args = build_args(jobs_path, tmp, max_inflight=1)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(
                FakeApi(fail_task_ids={"task-1"}), args, jobs, manifest, sleep=lambda _: None
            )
            by_id = {row["id"]: row for row in read_manifest(manifest)}

        self.assertEqual((1, 1), (succeeded, failed))
        self.assertEqual("failed", by_id["j1"]["status"])
        self.assertEqual("succeeded", by_id["j2"]["status"])

    def test_queue_full_submission_is_retried_not_failed(self) -> None:
        """A 429 means the server queue is full, so the job is retried later."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"
            api = FakeApi(submit_status_codes=[429, 429])

            succeeded, failed = run_batch(api, args, jobs, manifest, sleep=lambda _: None)

        self.assertEqual((1, 0), (succeeded, failed))
        self.assertEqual(["task-1"], api.submitted)

    def test_submit_error_other_than_queue_full_fails_the_job(self) -> None:
        """A non-429 HTTP error is a real submission failure."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(
                FakeApi(submit_status_codes=[500]), args, jobs, manifest, sleep=lambda _: None
            )
            rows = read_manifest(manifest)

        self.assertEqual((0, 1), (succeeded, failed))
        self.assertIn("submit failed", rows[0]["error"])

    def test_stall_only_fails_the_inflight_job_and_the_batch_continues(self) -> None:
        """A stall must fail only the stuck task, not every unsubmitted job.

        Both jobs here stall in turn (each is the sole in-flight task when the
        stall fires), so both still end up failed -- but each is only failed
        after actually being submitted, never pre-emptively.
        """

        clock = [0.0]

        def fake_sleep(seconds: float) -> None:
            clock[0] += max(seconds, 1.0)

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}', '{"id": "j2"}'])
            args = build_args(jobs_path, tmp, max_inflight=1, timeout=5)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(
                FakeApi(polls_before_done=10**6),
                args,
                jobs,
                manifest,
                sleep=fake_sleep,
                monotonic=lambda: clock[0],
            )
            by_id = {row["id"]: row for row in read_manifest(manifest)}

        self.assertEqual((0, 2), (succeeded, failed))
        self.assertEqual("batch stalled", by_id["j1"]["error"])
        self.assertEqual("batch stalled", by_id["j2"]["error"])

    def test_batch_recovers_after_one_stall_and_finishes_the_rest(self) -> None:
        """A job stuck forever must not condemn jobs that would otherwise finish."""

        clock = [0.0]

        def fake_sleep(seconds: float) -> None:
            clock[0] += max(seconds, 1.0)

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}', '{"id": "j2"}', '{"id": "j3"}'])
            args = build_args(jobs_path, tmp, max_inflight=1, timeout=5)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            # j1 becomes task-1 and never completes; j2/j3 complete normally.
            succeeded, failed = run_batch(
                FakeApi(polls_before_done=1, stalled_task_ids={"task-1"}),
                args,
                jobs,
                manifest,
                sleep=fake_sleep,
                monotonic=lambda: clock[0],
            )
            by_id = {row["id"]: row for row in read_manifest(manifest)}

        self.assertEqual((2, 1), (succeeded, failed))
        self.assertEqual("batch stalled", by_id["j1"]["error"])
        self.assertEqual("succeeded", by_id["j2"]["status"])
        self.assertEqual("succeeded", by_id["j3"]["status"])

    def test_repeated_stalls_with_no_success_abort_after_the_cap(self) -> None:
        """A permanently dead server must not cost ``timeout`` seconds per job."""

        clock = [0.0]

        def fake_sleep(seconds: float) -> None:
            clock[0] += max(seconds, 1.0)

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, [json.dumps({"id": f"j{i}"}) for i in range(5)])
            args = build_args(jobs_path, tmp, max_inflight=1, timeout=5)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            # Nothing ever completes, so every stall counts toward the cap.
            succeeded, failed = run_batch(
                FakeApi(polls_before_done=10**6),
                args,
                jobs,
                manifest,
                sleep=fake_sleep,
                monotonic=lambda: clock[0],
            )
            by_id = {row["id"]: row for row in read_manifest(manifest)}

        self.assertEqual((0, 5), (succeeded, failed))
        # The first 3 jobs were each submitted and stalled in turn (hitting
        # the cap); the last 2 never got the chance to submit.
        for job_id in ("j0", "j1", "j2"):
            self.assertEqual("batch stalled", by_id[job_id]["error"])
        for job_id in ("j3", "j4"):
            self.assertEqual("batch stalled before submission", by_id[job_id]["error"])

    def test_stall_counter_resets_on_any_terminal_completion_not_only_success(self) -> None:
        """A genuine task failure proves the server is alive, same as a success.

        j0 stalls (1 stall), j1 fails for real (proving the server answered),
        then j2 and j3 stall. If the stall streak only reset on success, that
        would be 3 stalls total against a cap of 3 and the batch would abort
        before j4 ever got a chance to submit. Because a real completion
        resets the streak too, only 2 stalls have happened since j1's
        failure, so the batch keeps going and j4 runs to completion.
        """

        clock = [0.0]

        def fake_sleep(seconds: float) -> None:
            clock[0] += max(seconds, 1.0)

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(
                tmp, [json.dumps({"id": f"j{i}"}) for i in range(5)]
            )
            args = build_args(jobs_path, tmp, max_inflight=1, timeout=5)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            # Submission order is j0..j4 -> task-1..task-5.
            succeeded, failed = run_batch(
                FakeApi(
                    stalled_task_ids={"task-1", "task-3", "task-4"},
                    fail_task_ids={"task-2"},
                ),
                args,
                jobs,
                manifest,
                sleep=fake_sleep,
                monotonic=lambda: clock[0],
            )
            by_id = {row["id"]: row for row in read_manifest(manifest)}

        self.assertEqual(5, succeeded + failed)
        # The cap-triggering scenario would leave j4 unsubmitted; proving it
        # ran to completion shows the streak did not wrongly accumulate.
        self.assertEqual("succeeded", by_id["j4"]["status"])

    def test_completion_submits_the_next_job_without_waiting(self) -> None:
        """A finished job must free the worker immediately, not after a poll interval."""

        sleeps: list[float] = []

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}', '{"id": "j2"}'])
            args = build_args(jobs_path, tmp, max_inflight=1, poll_interval=2)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(
                FakeApi(), args, jobs, manifest, sleep=sleeps.append
            )

        self.assertEqual((2, 0), (succeeded, failed))
        self.assertEqual([], sleeps)

    def test_no_progress_still_waits_between_polls(self) -> None:
        """Without a completion the runner must back off by the poll interval."""

        sleeps: list[float] = []

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp, poll_interval=2)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            run_batch(FakeApi(polls_before_done=4), args, jobs, manifest, sleep=sleeps.append)

        self.assertEqual([2.0, 2.0, 2.0], sleeps)

    def test_transient_poll_failure_is_retried(self) -> None:
        """A dropped connection while polling must not abort the batch."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(
                FakeApi(poll_connection_errors=3), args, jobs, manifest, sleep=lambda _: None
            )
            rows = read_manifest(manifest)

        self.assertEqual((1, 0), (succeeded, failed))
        self.assertEqual("succeeded", rows[0]["status"])

    def test_transient_submit_failure_is_retried(self) -> None:
        """A dropped connection while submitting must not fail the job."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            api = FakeApi(submit_connection_errors=2)
            succeeded, failed = run_batch(api, args, jobs, manifest, sleep=lambda _: None)
            rows = read_manifest(manifest)

        self.assertEqual((1, 0), (succeeded, failed))
        self.assertEqual(["task-1"], api.submitted)
        self.assertEqual("succeeded", rows[0]["status"])

    def test_unreachable_server_stops_at_the_stall_timeout(self) -> None:
        """Retrying an unreachable server must stay bounded by --timeout."""

        clock = [0.0]

        def fake_sleep(seconds: float) -> None:
            clock[0] += max(seconds, 1.0)

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp, timeout=5)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(
                FakeApi(submit_connection_errors=10**6),
                args,
                jobs,
                manifest,
                sleep=fake_sleep,
                monotonic=lambda: clock[0],
            )
            rows = read_manifest(manifest)

        self.assertEqual((0, 1), (succeeded, failed))
        self.assertEqual("batch stalled before submission", rows[0]["error"])

    def test_duplicate_task_id_does_not_lose_a_job(self) -> None:
        """A reused task_id must displace the earlier job with a manifest row, not silently drop it."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}', '{"id": "j2"}'])
            args = build_args(jobs_path, tmp, max_inflight=2)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(
                DuplicateTaskIdApi(), args, jobs, manifest, sleep=lambda _: None
            )
            rows = read_manifest(manifest)

        self.assertEqual(2, len(rows))
        self.assertEqual(succeeded + failed, len(jobs))
        by_id = {row["id"]: row for row in rows}
        self.assertEqual("failed", by_id["j1"]["status"])
        self.assertIn("reused", by_id["j1"]["error"])


class PollResilienceTests(unittest.TestCase):
    """A malformed /query_result response must not crash the batch."""

    def test_dict_shaped_response_is_ignored_not_fatal(self) -> None:
        """A dict instead of a list must not raise, and must warn once.

        Iterating a dict yields its keys, so without the response-shape guard
        every key would be reported as its own malformed item -- a wall of
        warnings that names none of the shapes actually received.
        """

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                succeeded, failed = run_batch(
                    FakeApi(malformed_poll_responses=[{"code": 0, "message": "ok", "data": {}}]),
                    args,
                    jobs,
                    manifest,
                    sleep=lambda _: None,
                )

        self.assertEqual((1, 0), (succeeded, failed))
        warnings = [line for line in buffer.getvalue().splitlines() if "malformed" in line]
        self.assertEqual(1, len(warnings), warnings)
        self.assertIn("malformed response", warnings[0])

    def test_non_dict_item_in_response_is_skipped_not_fatal(self) -> None:
        """A list response containing a non-dict item must not raise."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            succeeded, failed = run_batch(
                FakeApi(malformed_poll_responses=[["not-a-dict-item"]]),
                args,
                jobs,
                manifest,
                sleep=lambda _: None,
            )

        self.assertEqual((1, 0), (succeeded, failed))


class MainErrorHandlingTests(unittest.TestCase):
    """``main`` must report failures cleanly instead of raising a traceback."""

    def test_run_batch_exception_is_reported_not_raised(self) -> None:
        """An unexpected exception mid-batch must print an error and return 1."""

        api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            with mock.patch("acestep.api_batch.requests.Session", return_value=api), mock.patch(
                "acestep.api_batch.run_batch", side_effect=RuntimeError("boom")
            ):
                exit_code = main(["--jobs", jobs_path, "--output-dir", tmp, "--poll-interval", "0.001"])

        self.assertEqual(1, exit_code)

    def test_keyboard_interrupt_returns_130_not_a_traceback(self) -> None:
        """Ctrl-C on a long batch must exit 130 with a summary, not a traceback."""

        api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            with mock.patch("acestep.api_batch.requests.Session", return_value=api), mock.patch(
                "acestep.api_batch.run_batch", side_effect=KeyboardInterrupt
            ):
                exit_code = main(["--jobs", jobs_path, "--output-dir", tmp, "--poll-interval", "0.001"])

        self.assertEqual(130, exit_code)

    def test_run_batch_reports_totals_when_interrupted(self) -> None:
        """An interrupt mid-run must surface the totals accumulated so far."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}', '{"id": "j2"}'])
            args = build_args(jobs_path, tmp, max_inflight=1)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"

            def interrupting_sleep(_: float) -> None:
                raise KeyboardInterrupt

            buffer = io.StringIO()
            with self.assertRaises(KeyboardInterrupt), redirect_stdout(buffer):
                run_batch(
                    FakeApi(polls_before_done=10**6), args, jobs, manifest, sleep=interrupting_sleep
                )

        self.assertIn("succeeded=0", buffer.getvalue())
        self.assertIn("failed=0", buffer.getvalue())


class ResultIntegrityTests(unittest.TestCase):
    """A job only counts as succeeded when it really produced audio."""

    def _run_one(self, **api_kwargs) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp)
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"
            counts = run_batch(FakeApi(**api_kwargs), args, jobs, manifest, sleep=lambda _: None)
            rows = read_manifest(manifest)
        return {"counts": counts, "row": rows[0]}

    def test_success_without_audio_is_recorded_as_failed(self) -> None:
        """An empty result list must not be resumed away as a success."""

        outcome = self._run_one(empty_result_task_ids={"task-1"})
        self.assertEqual((0, 1), outcome["counts"])
        self.assertEqual("failed", outcome["row"]["status"])
        self.assertIn("no audio", outcome["row"]["error"])

    def test_unknown_status_is_recorded_as_failed(self) -> None:
        """A status this client does not know is a failure, not a success."""

        outcome = self._run_one(unknown_status_task_ids={"task-1"})
        self.assertEqual((0, 1), outcome["counts"])
        self.assertEqual("failed", outcome["row"]["status"])

    def test_no_download_mode_drops_placeholder_entries(self) -> None:
        """``--no-download`` must not report an empty file URL as a result."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            args = build_args(jobs_path, tmp)
            args.no_download = True
            jobs = load_jobs(jobs_path, args)
            manifest = Path(tmp) / "manifest.jsonl"
            counts = run_batch(
                FakeApi(empty_result_task_ids={"task-1"}), args, jobs, manifest, sleep=lambda _: None
            )
            row = read_manifest(manifest)[0]

        self.assertEqual((0, 1), counts)
        self.assertEqual("failed", row["status"])


class AuthenticationTests(unittest.TestCase):
    """``--api-key`` must reach every request, downloads included."""

    def test_api_key_authenticates_the_whole_session(self) -> None:
        """``GET /v1/audio`` is auth-gated, so the session must carry the key."""

        api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            with mock.patch("acestep.api_batch.requests.Session", return_value=api):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--poll-interval", "0.001",
                    "--api-key", "sk-test",
                ])

        self.assertEqual(0, exit_code)
        self.assertEqual("Bearer sk-test", api.headers.get("Authorization"))
        self.assertEqual(1, api.download_count)


class MainResumeTests(unittest.TestCase):
    """``main`` must honour manifest-driven resume, not just ``run_batch``."""

    def test_resume_skips_job_already_recorded_succeeded(self) -> None:
        """A manifest row with status succeeded must stop ``main`` from resubmitting that job."""

        api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1", "prompt": "a"}', '{"id": "j2", "prompt": "b"}'])
            manifest_path = Path(tmp) / "manifest.jsonl"
            manifest_path.write_text('{"id": "j1", "status": "succeeded"}\n', encoding="utf-8")

            buffer = io.StringIO()
            with mock.patch("acestep.api_batch.requests.Session", return_value=api), redirect_stdout(buffer):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--manifest", str(manifest_path),
                    "--poll-interval", "0.001",
                ])

        self.assertEqual(0, exit_code)
        self.assertEqual(["task-1"], api.submitted)
        self.assertIn("resume: skipping 1 job(s) already succeeded", buffer.getvalue())

    def test_no_resume_reruns_a_job_already_recorded_succeeded(self) -> None:
        """``--no-resume`` must ignore the manifest and resubmit every job."""

        api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1", "prompt": "a"}', '{"id": "j2", "prompt": "b"}'])
            manifest_path = Path(tmp) / "manifest.jsonl"
            manifest_path.write_text('{"id": "j1", "status": "succeeded"}\n', encoding="utf-8")

            with mock.patch("acestep.api_batch.requests.Session", return_value=api):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--manifest", str(manifest_path),
                    "--poll-interval", "0.001",
                    "--no-resume",
                ])

        self.assertEqual(0, exit_code)
        self.assertEqual(2, len(api.submitted))

    def test_resume_skips_entire_batch_when_all_jobs_already_succeeded(self) -> None:
        """When resume leaves nothing to do, ``main`` must report that and not touch the session."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1", "prompt": "a"}'])
            manifest_path = Path(tmp) / "manifest.jsonl"
            manifest_path.write_text('{"id": "j1", "status": "succeeded"}\n', encoding="utf-8")

            buffer = io.StringIO()
            # Nothing should reach the session, but assert that against a FakeApi
            # rather than leaving it unpatched or using a MagicMock. Unpatched, a
            # regression fires real HTTP at whatever is listening on the default
            # base URL; a MagicMock never returns a terminal status, so the poll
            # loop spins until the stall timeout instead of failing.
            api = FakeApi()
            with mock.patch("acestep.api_batch.requests.Session", return_value=api), redirect_stdout(buffer):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--manifest", str(manifest_path),
                    "--poll-interval", "0.001",
                ])

        self.assertEqual(0, exit_code)
        self.assertIn("nothing to do", buffer.getvalue())
        self.assertEqual([], api.submitted)


class MainDefaultManifestPathTests(unittest.TestCase):
    """Without ``--manifest``, ``main`` must default to ``<output-dir>/manifest.jsonl``."""

    def test_default_manifest_path_is_output_dir_manifest_jsonl(self) -> None:
        """The manifest must land under ``--output-dir``, not the current directory."""

        api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            with mock.patch("acestep.api_batch.requests.Session", return_value=api):
                exit_code = main(["--jobs", jobs_path, "--output-dir", tmp, "--poll-interval", "0.001"])
            expected_manifest = Path(tmp) / "manifest.jsonl"
            manifest_exists = expected_manifest.exists()
            rows = read_manifest(expected_manifest) if manifest_exists else []

        self.assertEqual(0, exit_code)
        self.assertTrue(manifest_exists)
        self.assertEqual("succeeded", rows[0]["status"])


class MainMaxInflightValidationTests(unittest.TestCase):
    """``main`` must reject a non-positive ``--max-inflight`` before submitting anything."""

    def test_max_inflight_zero_is_rejected_with_a_clean_error(self) -> None:
        """A zero max-inflight must fail with the documented message and exit code, no traceback."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--poll-interval", "0.001",
                    "--max-inflight", "0",
                ])

        self.assertEqual(1, exit_code)
        self.assertIn("--max-inflight must be >= 1", buffer.getvalue())


class MainMissingJobsFileTests(unittest.TestCase):
    """A nonexistent jobs file must produce a clean error, not a traceback."""

    def test_missing_jobs_file_reports_clean_error_and_exit_code_1(self) -> None:
        """Reading a jobs file that does not exist must be caught and reported, not raised."""

        with tempfile.TemporaryDirectory() as tmp:
            missing_path = str(Path(tmp) / "nope.jsonl")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["--jobs", missing_path, "--output-dir", tmp, "--poll-interval", "0.001"])

        self.assertEqual(1, exit_code)
        self.assertTrue(buffer.getvalue().startswith("error:"))


class ModuleEntryPointTests(unittest.TestCase):
    """Both CLIs must be runnable as ``python -m``, not just importable."""

    def _run_help(self, module: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", module, "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_api_client_is_runnable_as_a_module(self):
        result = self._run_help("acestep.api_client")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--base-url", result.stdout)

    def test_api_batch_is_runnable_as_a_module(self):
        result = self._run_help("acestep.api_batch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--jobs", result.stdout)



def make_audio_files(directory: str, names: list[str]) -> list[Path]:
    """Create placeholder audio files and return their paths."""

    paths = []
    for name in names:
        path = Path(directory) / name
        path.write_bytes(b"audio")
        paths.append(path)
    return paths


class OrderedManifestFilesTests(unittest.TestCase):
    """``ordered_manifest_files`` decides what --concat joins, and in what order."""

    def test_order_follows_the_jobs_file_not_the_manifest(self) -> None:
        """Completion order is not album order, so the jobs file must win."""

        with tempfile.TemporaryDirectory() as tmp:
            make_audio_files(tmp, ["a.flac", "b.flac"])
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}', '{"id": "j2"}'])
            jobs = load_jobs(jobs_path, build_args(jobs_path, tmp))
            manifest = Path(tmp) / "manifest.jsonl"
            # j2 finished first, so it is the earlier manifest row.
            append_manifest_row(manifest, {"id": "j2", "status": "succeeded", "files": [f"{tmp}/b.flac"]})
            append_manifest_row(manifest, {"id": "j1", "status": "succeeded", "files": [f"{tmp}/a.flac"]})

            files = ordered_manifest_files(jobs, manifest)

        self.assertEqual(["a.flac", "b.flac"], [path.name for path in files])

    def test_all_of_a_jobs_files_are_kept_in_recorded_order(self) -> None:
        """A job with batch_size > 1 contributes every variation it produced."""

        with tempfile.TemporaryDirectory() as tmp:
            make_audio_files(tmp, ["j1_0.flac", "j1_1.flac"])
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            jobs = load_jobs(jobs_path, build_args(jobs_path, tmp))
            manifest = Path(tmp) / "manifest.jsonl"
            append_manifest_row(
                manifest,
                {"id": "j1", "status": "succeeded", "files": [f"{tmp}/j1_0.flac", f"{tmp}/j1_1.flac"]},
            )

            files = ordered_manifest_files(jobs, manifest)

        self.assertEqual(["j1_0.flac", "j1_1.flac"], [path.name for path in files])

    def test_latest_succeeded_row_wins_for_a_rerun_job(self) -> None:
        """--no-resume leaves two succeeded rows for one job; the album wants the new audio."""

        with tempfile.TemporaryDirectory() as tmp:
            make_audio_files(tmp, ["old.flac", "new.flac"])
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            jobs = load_jobs(jobs_path, build_args(jobs_path, tmp))
            manifest = Path(tmp) / "manifest.jsonl"
            append_manifest_row(manifest, {"id": "j1", "status": "succeeded", "files": [f"{tmp}/old.flac"]})
            append_manifest_row(manifest, {"id": "j1", "status": "succeeded", "files": [f"{tmp}/new.flac"]})

            files = ordered_manifest_files(jobs, manifest)

        self.assertEqual(["new.flac"], [path.name for path in files])

    def test_failed_and_unrecorded_jobs_are_reported_and_skipped(self) -> None:
        """A gap in the album must be named, not silently closed up."""

        with tempfile.TemporaryDirectory() as tmp:
            make_audio_files(tmp, ["a.flac"])
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}', '{"id": "j2"}', '{"id": "j3"}'])
            jobs = load_jobs(jobs_path, build_args(jobs_path, tmp))
            manifest = Path(tmp) / "manifest.jsonl"
            append_manifest_row(manifest, {"id": "j1", "status": "succeeded", "files": [f"{tmp}/a.flac"]})
            append_manifest_row(manifest, {"id": "j2", "status": "failed", "error": "boom"})

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                files = ordered_manifest_files(jobs, manifest)

        self.assertEqual(["a.flac"], [path.name for path in files])
        self.assertIn("skipping j2", buffer.getvalue())
        self.assertIn("skipping j3", buffer.getvalue())

    def test_a_file_deleted_since_the_run_is_reported_and_skipped(self) -> None:
        """A stale manifest must not make ffmpeg fail on a path that no longer exists."""

        with tempfile.TemporaryDirectory() as tmp:
            make_audio_files(tmp, ["kept.flac"])
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            jobs = load_jobs(jobs_path, build_args(jobs_path, tmp))
            manifest = Path(tmp) / "manifest.jsonl"
            append_manifest_row(
                manifest,
                {"id": "j1", "status": "succeeded", "files": [f"{tmp}/gone.flac", f"{tmp}/kept.flac"]},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                files = ordered_manifest_files(jobs, manifest)

        self.assertEqual(["kept.flac"], [path.name for path in files])
        self.assertIn("gone.flac", buffer.getvalue())

    def test_missing_manifest_yields_no_files(self) -> None:
        """--concat before any run must not raise on a manifest that is not there."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1"}'])
            jobs = load_jobs(jobs_path, build_args(jobs_path, tmp))

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                files = ordered_manifest_files(jobs, Path(tmp) / "absent.jsonl")

        self.assertEqual([], files)


class ConcatAudioFilesTests(unittest.TestCase):
    """``concat_audio_files`` drives ffmpeg, so the command it builds is the contract."""

    @staticmethod
    def _capture_listing(recorder: dict):
        """Return a subprocess.run stub that records argv and the concat list."""

        def fake_run(argv, **kwargs):
            recorder["argv"] = argv
            recorder["listing"] = Path(argv[argv.index("-i") + 1]).read_text(encoding="utf-8")
            Path(argv[-1]).write_bytes(b"joined")
            return subprocess.CompletedProcess(argv, 0, "", "")

        return fake_run

    @staticmethod
    def _capture_argv(recorder: dict):
        """Return a subprocess.run stub for the filter path, which has no list file."""

        def fake_run(argv, **kwargs):
            recorder["argv"] = argv
            Path(argv[-1]).write_bytes(b"joined")
            return subprocess.CompletedProcess(argv, 0, "", "")

        return fake_run

    def test_empty_input_is_refused_before_ffmpeg_runs(self) -> None:
        """An album of nothing is a failure, not a zero-byte file."""

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("acestep.api_batch.subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError, "nothing to concatenate"):
                    concat_audio_files([], Path(tmp) / "album.mp3")
            run.assert_not_called()

    def test_missing_ffmpeg_is_reported_by_name(self) -> None:
        """The fix is "install ffmpeg", so the error has to say so."""

        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["a.flac"])
            with mock.patch("acestep.api_batch.shutil.which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "ffmpeg"):
                    concat_audio_files(files, Path(tmp) / "album.mp3")

    def test_inputs_are_passed_to_ffmpeg_via_the_concat_demuxer(self) -> None:
        """Every input must reach ffmpeg, in order, as an absolute path."""

        recorder: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["a.mp3", "b.mp3"])
            with mock.patch("acestep.api_batch.subprocess.run", self._capture_listing(recorder)):
                concat_audio_files(files, Path(tmp) / "album.mp3")

            self.assertEqual(
                f"file '{tmp}/a.mp3'\nfile '{tmp}/b.mp3'\n",
                recorder["listing"],
            )

        self.assertIn("-f", recorder["argv"])
        self.assertEqual("concat", recorder["argv"][recorder["argv"].index("-f") + 1])
        # Absolute paths are rejected by the demuxer unless -safe is off.
        self.assertEqual("0", recorder["argv"][recorder["argv"].index("-safe") + 1])

    def test_a_single_quote_in_a_path_is_escaped_for_the_demuxer(self) -> None:
        """The list format quotes with single quotes, so a literal one needs escaping.

        Unescaped, ffmpeg reads a truncated path and fails on a file that exists.
        """

        recorder: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["rock'n'roll.flac"])
            with mock.patch("acestep.api_batch.subprocess.run", self._capture_listing(recorder)):
                concat_audio_files(files, Path(tmp) / "album.flac")

            self.assertEqual(f"file '{tmp}/rock'\\''n'\\''roll.flac'\n", recorder["listing"])

    def test_mp3_output_overrides_ffmpegs_lossy_default_bitrate(self) -> None:
        """ffmpeg defaults mp3 to 128k; music deserves better than the default."""

        recorder: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["a.flac"])
            with mock.patch("acestep.api_batch.subprocess.run", self._capture_argv(recorder)):
                concat_audio_files(files, Path(tmp) / "album.mp3")

        self.assertIn("libmp3lame", recorder["argv"])
        self.assertEqual("2", recorder["argv"][recorder["argv"].index("-q:a") + 1])

    def test_matching_formats_are_copied_rather_than_re_encoded(self) -> None:
        """The server already returns lossy mp3; re-encoding it loses a generation for nothing."""

        recorder: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["a.mp3", "b.mp3"])
            with mock.patch("acestep.api_batch.subprocess.run", self._capture_listing(recorder)):
                concat_audio_files(files, Path(tmp) / "album.mp3")

        self.assertIn("-c", recorder["argv"])
        self.assertEqual("copy", recorder["argv"][recorder["argv"].index("-c") + 1])
        self.assertNotIn("libmp3lame", recorder["argv"])

    def test_mixed_input_formats_use_the_concat_filter_not_the_demuxer(self) -> None:
        """The demuxer silently drops tracks here, so mixed formats must avoid it.

        It reads the whole list with the first input's codec, so a flac decoder
        gets fed mp3 packets, discards every one of them, and ffmpeg still exits
        0 with an album missing all but its first song.
        """

        recorder: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["a.mp3", "b.flac"])
            with mock.patch("acestep.api_batch.subprocess.run", self._capture_argv(recorder)):
                concat_audio_files(files, Path(tmp) / "album.mp3")

            argv = recorder["argv"]
            self.assertNotIn("concat", argv[: argv.index("-filter_complex")])
            self.assertEqual(
                ["-i", f"{tmp}/a.mp3", "-i", f"{tmp}/b.flac"],
                argv[argv.index("-i") : argv.index("-filter_complex")],
            )

        self.assertEqual(
            "[0:a][1:a]concat=n=2:v=0:a=1[out]",
            argv[argv.index("-filter_complex") + 1],
        )
        self.assertEqual("[out]", argv[argv.index("-map") + 1])
        self.assertIn("libmp3lame", argv)

    def test_non_mp3_output_lets_ffmpeg_choose_the_codec(self) -> None:
        """Inputs it cannot copy and an output it has no bitrate opinion about.

        Mixed inputs rule out a copy, and forcing libmp3lame into a .flac
        container would fail outright, so ffmpeg picks the encoder itself.
        """

        recorder: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["a.mp3", "b.flac"])
            with mock.patch("acestep.api_batch.subprocess.run", self._capture_argv(recorder)):
                concat_audio_files(files, Path(tmp) / "album.flac")

        self.assertNotIn("libmp3lame", recorder["argv"])
        self.assertNotIn("-c:a", recorder["argv"])
        self.assertNotIn("-c", recorder["argv"])

    def test_ffmpeg_failure_surfaces_its_stderr(self) -> None:
        """ffmpeg's own message is the only useful diagnostic here."""

        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["a.flac"])
            failure = subprocess.CompletedProcess([], 1, "", "Invalid data found")
            with mock.patch("acestep.api_batch.subprocess.run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "Invalid data found"):
                    concat_audio_files(files, Path(tmp) / "album.mp3")

    def test_the_concat_list_is_cleaned_up_even_when_ffmpeg_fails(self) -> None:
        """The list file is scratch state; leaving it behind litters the output dir."""

        with tempfile.TemporaryDirectory() as tmp:
            files = make_audio_files(tmp, ["a.mp3"])
            failure = subprocess.CompletedProcess([], 1, "", "boom")
            with mock.patch("acestep.api_batch.subprocess.run", return_value=failure):
                with self.assertRaises(RuntimeError):
                    concat_audio_files(files, Path(tmp) / "album.mp3")

            leftovers = [path.name for path in Path(tmp).glob("*concat*")]

        self.assertEqual([], leftovers)


class MainConcatTests(unittest.TestCase):
    """--concat is wired into ``main`` after the batch, and gates its own exit code."""

    def test_concat_runs_after_a_successful_batch(self) -> None:
        """The whole point: generate the songs, then hand back one file."""

        api = FakeApi()
        recorder: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1", "prompt": "a"}', '{"id": "j2", "prompt": "b"}'])
            album = Path(tmp) / "album.mp3"

            buffer = io.StringIO()
            with mock.patch("acestep.api_batch.requests.Session", return_value=api), \
                 mock.patch("acestep.api_batch.subprocess.run",
                            ConcatAudioFilesTests._capture_listing(recorder)), \
                 redirect_stdout(buffer):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--poll-interval", "0.001",
                    "--concat", str(album),
                ])

            self.assertTrue(album.exists())

        self.assertEqual(0, exit_code)
        self.assertIn("j1_0", recorder["listing"])
        self.assertIn("j2_0", recorder["listing"])
        self.assertIn("[concat] wrote", buffer.getvalue())

    def test_concat_still_runs_when_resume_leaves_nothing_to_generate(self) -> None:
        """Rebuilding the album from an existing run must not regenerate anything."""

        api = FakeApi()
        recorder: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            make_audio_files(tmp, ["a.mp3"])
            jobs_path = write_jobs_file(tmp, ['{"id": "j1", "prompt": "a"}'])
            manifest_path = Path(tmp) / "manifest.jsonl"
            append_manifest_row(manifest_path, {"id": "j1", "status": "succeeded", "files": [f"{tmp}/a.mp3"]})
            album = Path(tmp) / "album.mp3"

            buffer = io.StringIO()
            with mock.patch("acestep.api_batch.requests.Session", return_value=api), \
                 mock.patch("acestep.api_batch.subprocess.run",
                            ConcatAudioFilesTests._capture_listing(recorder)), \
                 redirect_stdout(buffer):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--manifest", str(manifest_path),
                    "--poll-interval", "0.001",
                    "--concat", str(album),
                ])

        self.assertEqual(0, exit_code)
        self.assertEqual([], api.submitted)
        self.assertIn("nothing to do", buffer.getvalue())
        self.assertIn("a.mp3", recorder["listing"])

    def test_a_failed_concat_makes_the_run_fail(self) -> None:
        """Exiting 0 with no album would let a script carry on with nothing."""

        api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1", "prompt": "a"}'])
            failure = subprocess.CompletedProcess([], 1, "", "boom")

            buffer = io.StringIO()
            with mock.patch("acestep.api_batch.requests.Session", return_value=api), \
                 mock.patch("acestep.api_batch.subprocess.run", return_value=failure), \
                 redirect_stdout(buffer):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--poll-interval", "0.001",
                    "--concat", str(Path(tmp) / "album.mp3"),
                ])

        self.assertEqual(1, exit_code)
        self.assertIn("boom", buffer.getvalue())

    def test_concat_with_no_download_is_rejected_before_anything_is_queued(self) -> None:
        """--no-download records URLs, so there would be no local audio to join."""

        with tempfile.TemporaryDirectory() as tmp:
            jobs_path = write_jobs_file(tmp, ['{"id": "j1", "prompt": "a"}'])

            buffer = io.StringIO()
            # A FakeApi rather than a bare MagicMock: if the rejection is ever
            # dropped, the batch runs to completion against the fake and this
            # test fails on api.submitted, instead of polling a mock that never
            # reports a terminal status until the stall timeout expires.
            api = FakeApi()
            with mock.patch("acestep.api_batch.requests.Session", return_value=api), redirect_stdout(buffer):
                exit_code = main([
                    "--jobs", jobs_path,
                    "--output-dir", tmp,
                    "--poll-interval", "0.001",
                    "--no-download",
                    "--concat", str(Path(tmp) / "album.mp3"),
                ])

        self.assertEqual(1, exit_code)
        self.assertIn("--no-download", buffer.getvalue())
        self.assertEqual([], api.submitted)


if __name__ == "__main__":
    unittest.main()
