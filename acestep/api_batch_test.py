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
    load_completed_job_ids,
    load_jobs,
    main,
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


if __name__ == "__main__":
    unittest.main()
