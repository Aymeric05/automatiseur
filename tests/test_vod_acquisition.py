from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from twitch_auto_clipper.twitch_api import LiveStream, TwitchAPIError, TwitchVOD
from twitch_auto_clipper.twitch_monitor import MonitoringCycle, MonitoredStream
from twitch_auto_clipper.vod_acquisition import (
    MAX_ATTEMPTS,
    RETRY_BASE_SECONDS,
    TwitchVODAcquisitionManager,
    VOD_WAIT_SECONDS,
    find_downloaded_audio,
)


def monitored_stream(stream_id: str = "stream-1", budget: int = 5) -> MonitoredStream:
    return MonitoredStream(
        LiveStream(
            stream_id=stream_id,
            broadcaster_id="broadcaster-1",
            broadcaster_login="login",
            broadcaster_name="Broadcaster",
            viewer_count=10_000,
            title="Live title",
            game_name="Game",
            language="en",
            started_at="2026-09-25T12:00:00Z",
        ),
        budget,
    )


def vod(vod_id: str = "vod-1", stream_id: str = "stream-1") -> TwitchVOD:
    return TwitchVOD(vod_id, stream_id, "broadcaster-1", "Archive title")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class VODAcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.clock = Clock()
        self.client = Mock()
        self.client.find_vod_for_stream.return_value = vod()
        self.download = Mock(side_effect=self._fake_download)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _fake_download(self, url: str, input_dir: Path) -> Path:
        path = input_dir / f"{url.rsplit('/', 1)[-1]}_audio.mp4"
        path.write_bytes(b"audio")
        return path

    def manager(self) -> TwitchVODAcquisitionManager:
        return TwitchVODAcquisitionManager(
            api_client=self.client,
            input_dir=self.root / "input",
            state_path=self.root / "state" / "vods.json",
            downloader=self.download,
            clock=self.clock,
        )

    def state(self) -> dict:
        return json.loads((self.root / "state" / "vods.json").read_text(encoding="utf-8"))

    def test_ended_stream_is_queued_then_acquired_and_closed_once(self) -> None:
        manager = self.manager()
        cycle = MonitoringCycle(ended_streams=(monitored_stream(),))

        queued = manager.process_cycle(cycle)
        self.assertEqual(queued[0].status, "queued")
        self.client.find_vod_for_stream.assert_not_called()  # the monitoring thread never waits

        [acquisition] = list(manager.acquire_due())
        self.assertEqual((acquisition.status, acquisition.vod_id, acquisition.clip_budget), ("downloaded", "vod-1", 5))
        self.assertEqual(acquisition.downloaded_path, self.root / "input" / "vod-1_audio.mp4")
        self.download.assert_called_once_with("https://www.twitch.tv/videos/vod-1", self.root / "input")

        self.assertEqual(manager.record_automation("stream-1", "vod-1", "completed"), "done")
        self.assertEqual(list(manager.acquire_due()), [])
        self.assertEqual(manager.process_cycle(cycle)[0].status, "already_processed")
        self.assertEqual(self.state()["processed_streams"], {"stream-1": "vod-1"})
        self.assertEqual(self.state()["jobs"], {})
        self.download.assert_called_once()

    def test_queued_job_survives_a_restart_even_mid_processing(self) -> None:
        first = self.manager()
        first.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))
        list(first.acquire_due())  # crash before record_automation: job not closed

        restarted = self.manager()
        [acquisition] = list(restarted.acquire_due())
        self.assertEqual(acquisition.status, "already_downloaded")  # audio reused
        self.download.assert_called_once()

    def test_unavailable_vod_is_checked_again_without_spending_an_attempt(self) -> None:
        self.client.find_vod_for_stream.side_effect = [None, vod()]
        manager = self.manager()
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))

        self.assertEqual([a.status for a in manager.acquire_due()], ["vod_not_available"])
        self.assertEqual(list(manager.acquire_due()), [])  # not due yet
        self.assertEqual(self.state()["jobs"]["stream-1"]["attempts"], 0)
        self.clock.advance(RETRY_BASE_SECONDS)
        self.assertEqual([a.status for a in manager.acquire_due()], ["downloaded"])

    def test_vod_never_published_is_abandoned_after_a_day(self) -> None:
        self.client.find_vod_for_stream.return_value = None
        manager = self.manager()
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))
        self.clock.advance(VOD_WAIT_SECONDS + 1)

        [acquisition] = list(manager.acquire_due())
        self.assertEqual(acquisition.status, "abandoned")
        self.assertIn("stream-1", self.state()["abandoned"])
        self.assertEqual(manager.process_cycle(
            MonitoringCycle(ended_streams=(monitored_stream(),))
        )[0].status, "already_processed")

    def test_biggest_streams_are_processed_first(self) -> None:
        self.client.find_vod_for_stream.side_effect = lambda broadcaster, stream_id: vod(f"vod-{stream_id}", stream_id)
        manager = self.manager()
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream("small", budget=2),)))
        self.clock.advance(60)
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream("big", budget=10),)))
        self.assertEqual([a.stream_id for a in manager.acquire_due()], ["big", "small"])

    def test_top_streamer_gets_twenty_moments_and_carries_its_peak(self) -> None:
        manager = TwitchVODAcquisitionManager(
            api_client=self.client, input_dir=self.root / "input", state_path=self.root / "state" / "vods.json",
            downloader=self.download, clock=self.clock, top_streamers=frozenset({"LOGIN"}),
        )
        live = monitored_stream(budget=5)
        manager.process_cycle(MonitoringCycle(ended_streams=(live,)))
        [acquisition] = list(manager.acquire_due())
        self.assertEqual((acquisition.clip_budget, acquisition.peak_viewers), (20, 10_000))

    def test_biggest_peak_goes_first_even_if_it_ended_last(self) -> None:
        manager = self.manager()
        small, big = monitored_stream("stream-small", budget=5), monitored_stream("stream-big", budget=5)
        big = MonitoredStream(big.stream, 5, peak_viewer_count=57_000)
        manager.process_cycle(MonitoringCycle(ended_streams=(small,)))
        self.clock.advance(3600)
        manager.process_cycle(MonitoringCycle(ended_streams=(big,)))
        self.client.find_vod_for_stream.side_effect = lambda broadcaster, stream_id: vod(f"vod-{stream_id}", stream_id)
        order = [result.stream_id for result in manager.acquire_due()]
        self.assertEqual(order, ["stream-big", "stream-small"])

    def test_job_too_old_to_publish_is_dropped_with_its_audio(self) -> None:
        manager = self.manager()
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))
        list(manager.acquire_due())
        manager.record_automation("stream-1", "vod-1", "error", error="boom")
        audio = self.root / "input" / "vod-1_audio.mp4"
        self.assertTrue(audio.is_file())
        self.clock.advance(49 * 3600)
        self.assertEqual(list(manager.acquire_due()), [])  # dropped before any work
        self.assertFalse(audio.exists())
        self.assertEqual(manager.pending_jobs, 0)
        self.assertIn("trop ancien", self.state()["abandoned"]["stream-1"]["error"])

    def test_the_queue_keeps_only_the_jobs_it_can_process(self) -> None:
        from twitch_auto_clipper.vod_acquisition import MAX_QUEUED_JOBS

        manager = self.manager()
        streams = tuple(monitored_stream(f"stream-{i}", budget=2) for i in range(MAX_QUEUED_JOBS + 5))
        streams = tuple(MonitoredStream(s.stream, 2, peak_viewer_count=20000 + i) for i, s in enumerate(streams))
        manager.process_cycle(MonitoringCycle(ended_streams=streams))
        self.client.find_vod_for_stream.return_value = None  # nothing to download: only the purge matters
        list(manager.acquire_due())
        self.assertEqual(manager.pending_jobs, MAX_QUEUED_JOBS)
        self.assertNotIn("stream-0", self.state()["jobs"])  # the smallest peaks were dropped

    def test_a_blocked_streamer_is_never_queued_and_their_queued_vods_are_dropped(self) -> None:
        blocked = set()
        manager = TwitchVODAcquisitionManager(
            api_client=self.client, input_dir=self.root / "input", state_path=self.root / "state" / "vods.json",
            downloader=self.download, clock=self.clock, blocked_streamers=lambda: frozenset(blocked),
        )
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream("stream-1"),)))
        list(manager.acquire_due())
        manager.record_automation("stream-1", "vod-1", "error", error="boom")
        audio = self.root / "input" / "vod-1_audio.mp4"
        blocked.add("login")  # added while the app runs (a YouTube warning)
        self.assertEqual(list(manager.acquire_due()), [])  # dropped before any work
        self.assertFalse(audio.exists())
        self.assertIn("liste noire", self.state()["abandoned"]["stream-1"]["error"])
        result = manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream("stream-2"),)))
        self.assertEqual(result[0].status, "skipped_blocked")
        self.assertEqual(manager.pending_jobs, 0)

    def test_zero_budget_is_never_queued(self) -> None:
        manager = self.manager()
        result = manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(budget=0),)))
        self.assertEqual(result[0].status, "skipped_zero_budget")
        self.assertEqual(list(manager.acquire_due()), [])
        self.client.find_vod_for_stream.assert_not_called()

    def test_api_error_is_retried_later_with_a_growing_delay(self) -> None:
        self.client.find_vod_for_stream.side_effect = [TwitchAPIError("temporary"), vod()]
        manager = self.manager()
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))

        self.assertEqual([a.status for a in manager.acquire_due()], ["error"])
        self.assertEqual(self.state()["jobs"]["stream-1"]["attempts"], 1)
        self.assertEqual(list(manager.acquire_due()), [])
        self.clock.advance(RETRY_BASE_SECONDS)
        self.assertEqual([a.status for a in manager.acquire_due()], ["downloaded"])

    def test_pipeline_failures_are_retried_then_abandoned(self) -> None:
        manager = self.manager()
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))
        delays = []
        for attempt in range(1, MAX_ATTEMPTS + 1):
            [acquisition] = list(manager.acquire_due())
            outcome = manager.record_automation("stream-1", "vod-1", "error", error="Gemini indisponible")
            if attempt < MAX_ATTEMPTS:
                self.assertEqual(outcome, "retry")
                retry_at = datetime.fromisoformat(self.state()["jobs"]["stream-1"]["next_attempt_at"])
                delays.append((retry_at - self.clock.now).total_seconds())
                self.clock.now = retry_at
        self.assertEqual(outcome, "abandoned")
        self.assertEqual(delays[:3], [RETRY_BASE_SECONDS, 2 * RETRY_BASE_SECONDS, 4 * RETRY_BASE_SECONDS])
        self.assertEqual(self.state()["abandoned"]["stream-1"]["error"], "Gemini indisponible")
        self.assertTrue((self.root / "input" / "vod-1_audio.mp4").is_file())  # kept for inspection

    def test_waiting_for_the_upload_quota_spends_no_attempt(self) -> None:
        manager = self.manager()
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))
        list(manager.acquire_due())
        reset = self.clock.now + timedelta(hours=10)

        self.assertEqual(manager.record_automation("stream-1", "vod-1", "waiting_gemini", retry_at=reset), "waiting")
        job = self.state()["jobs"]["stream-1"]
        self.assertEqual((job["attempts"], datetime.fromisoformat(job["next_attempt_at"])), (0, reset))
        self.clock.now = reset
        self.assertEqual([a.status for a in manager.acquire_due()], ["already_downloaded"])
        later = self.clock.now + timedelta(hours=1)
        self.assertEqual(manager.record_automation("stream-1", "vod-1", "waiting_gemini", retry_at=later), "waiting")
        self.assertEqual(self.state()["jobs"]["stream-1"]["attempts"], 0)

    def test_low_disk_space_stops_before_downloading(self) -> None:
        manager = self.manager()
        manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))
        with patch("twitch_auto_clipper.vod_acquisition.shutil.disk_usage", return_value=Mock(free=10)):
            [acquisition] = list(manager.acquire_due())
        self.assertEqual(acquisition.status, "error")
        self.assertIn("espace disque insuffisant", acquisition.error)
        self.download.assert_not_called()

    def test_corrupt_state_is_reported_instead_of_ignored(self) -> None:
        (self.root / "state").mkdir()
        (self.root / "state" / "vods.json").write_text('{"jobs": {"s": {"stream": {}}}}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manager()

    def test_only_complete_audio_files_are_reused(self) -> None:
        directory = self.root / "input"
        directory.mkdir()
        (directory / "vod-1_audio.mp4.part").write_bytes(b"partial")
        (directory / "vod-1_audio.temp.mp4").write_bytes(b"fixup in progress")
        self.assertIsNone(find_downloaded_audio(directory, "vod-1"))
        (directory / "vod-1_audio.mp4").write_bytes(b"audio")
        self.assertEqual(find_downloaded_audio(directory, "vod-1"), directory / "vod-1_audio.mp4")


if __name__ == "__main__":
    unittest.main()
