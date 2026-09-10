"""Tests for the legacy ACE-Step async API client helpers."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from acestep.api_client import (
    build_release_task_payload,
    download_audio_files,
    infer_output_suffix,
    parse_query_result_item,
    poll_task_result,
    resolve_audio_url,
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

    def __init__(self, payload=None, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        """No-op: these tests never exercise an error status."""

    def json(self):
        """Return the canned JSON payload."""

        return self._payload


class _FakeDownloadSession:
    """Serves a fake audio GET for ``download_audio_files`` tests."""

    def get(self, url: str, **kwargs) -> _FakeResponse:
        """Return canned audio bytes regardless of the requested URL."""

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


if __name__ == "__main__":
    unittest.main()
