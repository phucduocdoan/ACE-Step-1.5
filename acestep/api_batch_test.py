"""Tests for the ACE-Step async API batch runner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path

import requests

from acestep.api_batch import (
    build_batch_arg_parser,
    load_completed_job_ids,
    load_jobs,
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
    ) -> None:
        self.polls_before_done = polls_before_done
        self.fail_task_ids = set(fail_task_ids)
        self.submit_status_codes = deque(submit_status_codes)
        self.submit_connection_errors = submit_connection_errors
        self.poll_connection_errors = poll_connection_errors
        self.submitted: list[str] = []
        self.polls: dict[str, int] = {}
        self.inflight = 0
        self.max_inflight_seen = 0
        self.download_count = 0

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
        items = []
        for task_id in task_ids:
            self.polls[task_id] = self.polls.get(task_id, 0) + 1
            if self.polls[task_id] < self.polls_before_done:
                items.append({"task_id": task_id, "status": 0, "result": "[]"})
                continue
            self.inflight -= 1
            if task_id in self.fail_task_ids:
                items.append({"task_id": task_id, "status": 2, "result": "[]"})
                continue
            result = json.dumps([{"file": f"/v1/audio?path=%2Ftmp%2F{task_id}.mp3", "status": 1}])
            items.append({"task_id": task_id, "status": 1, "result": result})
        return FakeResponse({"data": items})


def build_args(jobs_path: str, output_dir: str, **overrides):
    """Build a batch argument namespace with test-friendly defaults."""

    argv = [
        "--jobs", jobs_path,
        "--output-dir", output_dir,
        "--poll-interval", "0",
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

        self.assertEqual(["song-01", "job-0002"], [job.job_id for job in jobs])
        self.assertEqual("lofi", jobs[0].args.prompt)
        self.assertEqual(45, jobs[0].args.audio_duration)
        self.assertEqual(12, jobs[0].args.inference_steps)
        self.assertEqual(12, jobs[1].args.inference_steps)
        self.assertIsNone(jobs[1].args.audio_duration)

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

    def test_stall_timeout_aborts_and_records_remaining_jobs(self) -> None:
        """When nothing completes within the stall window the batch aborts."""

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
        self.assertEqual("batch stalled before submission", by_id["j2"]["error"])

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


if __name__ == "__main__":
    unittest.main()


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
