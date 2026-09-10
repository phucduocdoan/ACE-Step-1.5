"""Tests for the legacy ACE-Step async API client helpers."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional

import requests

from acestep.api_client import (
    build_release_task_payload,
    download_audio_files,
    infer_output_suffix,
    parse_query_result_item,
    poll_task_result,
    query_tasks,
    resolve_audio_url,
    submit_generation_task,
    validate_args,
)


class ApiClientValidationTests(unittest.TestCase):
    """Validate CLI argument rules for task-specific API modes."""

    def test_cover_requires_src_audio(self) -> None:
        """Cover-family tasks should require a source audio file."""

        args = argparse.Namespace(
            task_type="cover",
            src_audio=None,
            batch_size=1,
            poll_interval=2.0,
            repainting_end=None,
        )
        with self.assertRaisesRegex(ValueError, "--src-audio is required"):
            validate_args(args)

    def test_repaint_requires_end_time(self) -> None:
        """Repaint mode should require an explicit repaint end boundary."""

        args = argparse.Namespace(
            task_type="repaint",
            src_audio="input.wav",
            batch_size=1,
            poll_interval=2.0,
            repainting_end=None,
        )
        with self.assertRaisesRegex(ValueError, "--repainting-end is required"):
            validate_args(args)

    def test_poll_interval_must_be_positive(self) -> None:
        """A zero or negative poll interval must be rejected before any network call."""

        args = argparse.Namespace(
            task_type="text2music",
            src_audio=None,
            batch_size=1,
            poll_interval=0,
            repainting_end=None,
        )
        with self.assertRaisesRegex(ValueError, "--poll-interval must be > 0"):
            validate_args(args)


class ApiClientPayloadTests(unittest.TestCase):
    """Exercise request payload building for the release-task API."""

    def test_build_release_task_payload_disables_random_seed_when_seed_given(self) -> None:
        """Explicit seeds should set ``use_random_seed`` false in the payload."""

        args = argparse.Namespace(
            task_type="text2music",
            prompt="hello",
            lyrics="",
            thinking=False,
            vocal_language="en",
            batch_size=2,
            inference_steps=8,
            guidance_scale=7.0,
            audio_format="mp3",
            repainting_start=0.0,
            repainting_end=None,
            repaint_mode="balanced",
            repaint_strength=0.5,
            audio_duration=30.0,
            model="acestep-v15-xl-turbo",
            seed="42,43",
        )
        payload = build_release_task_payload(args)
        self.assertEqual("42,43", payload["seed"])
        self.assertFalse(payload["use_random_seed"])
        self.assertEqual(2, payload["batch_size"])

    def test_build_release_task_payload_includes_gradio_repaint_defaults(self) -> None:
        """Repaint requests should send the same default mode/strength as Gradio."""

        args = argparse.Namespace(
            task_type="repaint",
            prompt="repair the chorus",
            lyrics="[Instrumental]",
            thinking=False,
            vocal_language="en",
            batch_size=1,
            inference_steps=8,
            guidance_scale=7.0,
            audio_format="mp3",
            repainting_start=0.0,
            repainting_end=12.0,
            repaint_mode="balanced",
            repaint_strength=0.5,
            audio_duration=None,
            model=None,
            seed=None,
        )
        payload = build_release_task_payload(args)
        self.assertEqual("balanced", payload["repaint_mode"])
        self.assertEqual(0.5, payload["repaint_strength"])


class ApiClientResultParsingTests(unittest.TestCase):
    """Verify legacy query-result parsing and audio URL helpers."""

    def test_parse_query_result_item_handles_batch_audio_list(self) -> None:
        """Batch-sized generations should parse into one entry per returned audio."""

        item = {
            "result": (
                '[{"file":"/v1/audio?path=%2Ftmp%2Fa.mp3","status":1},'
                '{"file":"/v1/audio?path=%2Ftmp%2Fb.mp3","status":1}]'
            )
        }
        result = parse_query_result_item(item)
        self.assertEqual(2, len(result))
        self.assertEqual("/v1/audio?path=%2Ftmp%2Fb.mp3", result[1]["file"])

    def test_audio_url_helpers_preserve_relative_path_and_suffix(self) -> None:
        """Relative ``/v1/audio`` URLs should resolve and keep output suffixes."""

        file_url = "/v1/audio?path=%2Ftmp%2Fapi_audio%2Fdemo.flac"
        self.assertEqual("http://127.0.0.1:8001/v1/audio?path=%2Ftmp%2Fapi_audio%2Fdemo.flac", resolve_audio_url("http://127.0.0.1:8001", file_url))
        self.assertEqual(".flac", infer_output_suffix(file_url))


class _FakeResponse:
    """Minimal stand-in for a ``requests`` response object."""

    def __init__(
        self,
        payload=None,
        content: bytes = b"",
        status_code: int = 200,
        json_error: Optional[Exception] = None,
    ) -> None:
        self._payload = payload
        self.content = content
        self.status_code = status_code
        self._json_error = json_error

    def raise_for_status(self) -> None:
        """Raise for error status codes the way ``requests`` does."""

        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        """Return the canned JSON payload, or raise a canned decode error."""

        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _FakeDownloadSession:
    """Serves a fake audio GET for ``download_audio_files`` tests."""

    def __init__(self, responses: Optional[list] = None) -> None:
        self.urls: list[str] = []
        # Canned responses returned in order; falls back to a fixed success
        # response when not given, matching the previous unconditional behaviour.
        self.responses = list(responses) if responses is not None else None

    def get(self, url: str, **kwargs) -> _FakeResponse:
        """Record the requested URL and return a canned (or default) response."""

        self.urls.append(url)
        if self.responses is not None:
            return self.responses.pop(0)
        return _FakeResponse(content=b"audio-bytes")


class DownloadAudioFilesTests(unittest.TestCase):
    """Downloaded files must never land outside the requested output directory."""

    def test_file_prefix_cannot_escape_output_dir(self) -> None:
        """A path-shaped prefix (a job id or server task_id) must stay inside output_dir."""

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            saved = download_audio_files(
                session=_FakeDownloadSession(),
                base_url="http://127.0.0.1:8001",
                audio_items=[{"file": "/v1/audio?path=%2Ftmp%2Fx.mp3"}],
                output_dir=str(out_dir),
                file_prefix="../escaped",
            )

        self.assertEqual(1, len(saved))
        self.assertEqual(out_dir, saved[0].parent)


class DownloadAudioFilesUrlAndSuffixTests(unittest.TestCase):
    """The download path must resolve each item's URL and index filenames correctly."""

    def test_relative_file_urls_resolve_against_base_url(self) -> None:
        """The GET must hit the base URL joined with the item's relative file URL."""

        session = _FakeDownloadSession()
        with tempfile.TemporaryDirectory() as tmp:
            download_audio_files(
                session=session,
                base_url="http://127.0.0.1:8001",
                audio_items=[{"file": "/v1/audio?path=%2Ftmp%2Fa.mp3"}],
                output_dir=tmp,
                file_prefix="job",
            )

        self.assertEqual(["http://127.0.0.1:8001/v1/audio?path=%2Ftmp%2Fa.mp3"], session.urls)

    def test_items_missing_a_file_field_are_skipped_but_still_consume_an_index(self) -> None:
        """A skipped item must not shift the index used by later filenames.

        The output index comes from ``enumerate(audio_items)``, not from a count
        of files actually downloaded, so a blank entry ahead of a real one must
        leave that real file numbered by its original position.
        """

        session = _FakeDownloadSession()
        with tempfile.TemporaryDirectory() as tmp:
            saved = download_audio_files(
                session=session,
                base_url="http://127.0.0.1:8001",
                audio_items=[{"file": ""}, {"file": "/v1/audio?path=%2Ftmp%2Fb.flac"}],
                output_dir=tmp,
                file_prefix="job",
            )

        self.assertEqual(1, len(saved))
        self.assertEqual("job_1.flac", saved[0].name)

    def test_http_error_status_propagates_from_the_download(self) -> None:
        """A failed audio download must raise, not silently write an empty file."""

        session = _FakeDownloadSession(responses=[_FakeResponse(status_code=500)])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(requests.HTTPError):
                download_audio_files(
                    session=session,
                    base_url="http://127.0.0.1:8001",
                    audio_items=[{"file": "/v1/audio?path=%2Ftmp%2Fa.mp3"}],
                    output_dir=tmp,
                    file_prefix="job",
                )


class _FakeApiSession:
    """Serves canned POST responses in order, for submit/query error-path tests.

    Mirrors ``_FakePollSession``'s indexing: the last response repeats once
    the list is exhausted, so a single-entry list is enough for tests that
    only ever make one call.
    """

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls = 0

    def post(self, url: str, **kwargs) -> _FakeResponse:
        """Return the next canned response, repeating the last one after exhaustion."""

        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class SubmitGenerationTaskTests(unittest.TestCase):
    """Exercise the ``/release_task`` submission helper's response handling."""

    def test_raises_for_http_error_status(self) -> None:
        """A 5xx response must surface as an ``HTTPError``, not a swallowed failure."""

        session = _FakeApiSession([_FakeResponse(status_code=500)])
        with self.assertRaises(requests.HTTPError):
            submit_generation_task(
                session=session,
                base_url="http://127.0.0.1:8001",
                api_key=None,
                payload={"task_type": "text2music"},
            )

    def test_raises_when_body_is_not_json(self) -> None:
        """A non-JSON body must propagate the decode error, not be misread as empty."""

        session = _FakeApiSession(
            [_FakeResponse(json_error=json.JSONDecodeError("Expecting value", "", 0))]
        )
        with self.assertRaises(json.JSONDecodeError):
            submit_generation_task(
                session=session,
                base_url="http://127.0.0.1:8001",
                api_key=None,
                payload={"task_type": "text2music"},
            )

    def test_raises_when_response_has_no_task_id(self) -> None:
        """A 200 response missing ``data.task_id`` must fail loudly, not return ``None``."""

        session = _FakeApiSession([_FakeResponse({"data": {}})])
        with self.assertRaisesRegex(RuntimeError, "did not return a task_id"):
            submit_generation_task(
                session=session,
                base_url="http://127.0.0.1:8001",
                api_key=None,
                payload={"task_type": "text2music"},
            )

    def test_returns_task_id_on_success(self) -> None:
        """A well-formed response must yield the queued task ID."""

        session = _FakeApiSession([_FakeResponse({"data": {"task_id": "t-123"}})])
        task_id = submit_generation_task(
            session=session,
            base_url="http://127.0.0.1:8001",
            api_key=None,
            payload={"task_type": "text2music"},
        )

        self.assertEqual("t-123", task_id)


class QueryTasksTests(unittest.TestCase):
    """Exercise the ``/query_result`` polling helper's response handling."""

    def test_raises_for_http_error_status(self) -> None:
        """A 5xx response must surface as an ``HTTPError``."""

        session = _FakeApiSession([_FakeResponse(status_code=503)])
        with self.assertRaises(requests.HTTPError):
            query_tasks(session, "http://127.0.0.1:8001", None, ["t1"])

    def test_raises_when_body_is_not_json(self) -> None:
        """A non-JSON body must propagate the decode error."""

        session = _FakeApiSession(
            [_FakeResponse(json_error=json.JSONDecodeError("Expecting value", "", 0))]
        )
        with self.assertRaises(json.JSONDecodeError):
            query_tasks(session, "http://127.0.0.1:8001", None, ["t1"])

    def test_missing_data_field_returns_empty_list(self) -> None:
        """A response with no ``data`` field must yield ``[]``, not raise."""

        session = _FakeApiSession([_FakeResponse({"code": 0})])
        self.assertEqual([], query_tasks(session, "http://127.0.0.1:8001", None, ["t1"]))

    def test_returns_data_list_on_success(self) -> None:
        """A well-formed response must yield the ``data`` list unchanged."""

        session = _FakeApiSession([_FakeResponse({"data": [{"task_id": "t1", "status": 1}]})])
        result = query_tasks(session, "http://127.0.0.1:8001", None, ["t1"])

        self.assertEqual([{"task_id": "t1", "status": 1}], result)


class _FakePollSession:
    """Serves canned ``/query_result`` responses to test ``poll_task_result``."""

    def __init__(self, statuses: list[int], max_polls: Optional[int] = None) -> None:
        self.statuses = list(statuses)
        self.calls = 0
        self.max_polls = max_polls

    def post(self, url: str, **kwargs) -> _FakeResponse:
        """Return the next canned status, refusing to be polled past the budget."""

        if self.max_polls is not None and self.calls >= self.max_polls:
            raise AssertionError(f"polled more than {self.max_polls} times")
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        return _FakeResponse({"data": [{"task_id": "t1", "status": status, "result": "[]"}]})


class PollTaskResultTests(unittest.TestCase):
    """The polling deadline must use a monotonic clock, and be injectable."""

    def test_uses_injected_monotonic_clock_and_sleep(self) -> None:
        """Both the deadline and the wait must go through the injected callables."""

        clock = [0.0]
        sleeps: list[float] = []

        def fake_monotonic() -> float:
            return clock[0]

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        result = poll_task_result(
            session=_FakePollSession([0, 0, 1]),
            base_url="http://127.0.0.1:8001",
            api_key=None,
            task_id="t1",
            poll_interval=1.0,
            timeout=10.0,
            sleep=fake_sleep,
            monotonic=fake_monotonic,
        )

        self.assertEqual([], result)
        self.assertEqual([1.0, 1.0], sleeps)

    def test_times_out_using_the_injected_clock_not_wall_time(self) -> None:
        """The deadline must advance with the injected clock, not the wall clock.

        ``timeout=2.5`` with ``poll_interval=1.0`` allows exactly three polls
        (at clock 0, 1 and 2). A deadline read from ``time.time()`` ignores the
        injected clock entirely and spins until 2.5 real seconds have passed,
        so it blows through that budget -- which is what ``max_polls`` catches.
        """

        clock = [0.0]

        def fake_monotonic() -> float:
            return clock[0]

        def fake_sleep(seconds: float) -> None:
            clock[0] += seconds

        session = _FakePollSession([0], max_polls=3)
        with self.assertRaises(TimeoutError):
            poll_task_result(
                session=session,
                base_url="http://127.0.0.1:8001",
                api_key=None,
                task_id="t1",
                poll_interval=1.0,
                timeout=2.5,
                sleep=fake_sleep,
                monotonic=fake_monotonic,
            )

        self.assertEqual(3, session.calls)

    def test_raises_on_task_failure_status(self) -> None:
        """Status 2 (failed) must raise, not be treated as still pending."""

        with self.assertRaisesRegex(RuntimeError, "task failed"):
            poll_task_result(
                session=_FakePollSession([2]),
                base_url="http://127.0.0.1:8001",
                api_key=None,
                task_id="t1",
                poll_interval=1.0,
                timeout=10.0,
                sleep=lambda _: None,
                monotonic=lambda: 0.0,
            )


if __name__ == "__main__":
    unittest.main()
