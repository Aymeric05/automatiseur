"""Live clipping (LIVE_CLIPPING=1): a stream is processed in parts while still live."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from unittest.mock import Mock

from twitch_auto_clipper.twitch import vod_url
from twitch_auto_clipper.twitch_api import LiveStream, TwitchVOD
from twitch_auto_clipper.twitch_monitor import MonitoredStream, MonitoringCycle
from twitch_auto_clipper.vod_acquisition import (
    LIVE_LAG_SECONDS,
    LIVE_PART_KEEP_LEAD,
    LIVE_PART_LEAD,
    LIVE_PART_SECONDS,
    TwitchVODAcquisitionManager,
)

STARTED = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def live(budget=5):
    stream = LiveStream(stream_id="s1", broadcaster_id="b1", broadcaster_login="kai", broadcaster_name="Kai",
                        viewer_count=20_000, title="t", game_name="Fortnite", language="en",
                        started_at=STARTED.isoformat().replace("+00:00", "Z"))
    return MonitoredStream(stream, budget)


def test_vod_url_names_the_vod_of_a_live_part():
    assert vod_url("2932194507p3") == vod_url("2932194507") == "https://www.twitch.tv/videos/2932194507"


def test_a_live_stream_is_processed_in_parts_then_its_last_part_once_it_ends():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        clock = [STARTED + timedelta(seconds=LIVE_PART_SECONDS)]
        downloads = []

        def download(url, folder, section=None, name=None):
            downloads.append((url, section, name))
            path = folder / f"{name}_audio.mp4"
            path.write_bytes(b"audio")
            return path

        client = Mock()
        client.find_vod_for_stream.return_value = TwitchVOD("777", "s1", "b1", "title")
        client.fetch_vod.return_value = None  # length unknown: windows kept as cut
        manager = TwitchVODAcquisitionManager(api_client=client, input_dir=root / "in", state_path=root / "s.json",
                                              downloader=download, clock=lambda: clock[0], live_parts=True)
        cycle = MonitoringCycle(streams=(live(),))
        assert manager.process_cycle(cycle) == ()  # not 2 hours on Twitch yet (the VOD lags behind)

        clock[0] += timedelta(seconds=LIVE_LAG_SECONDS)
        assert [r.status for r in manager.process_cycle(cycle)] == ["queued_part"]
        assert manager.process_cycle(cycle) == ()  # queued once
        [first] = list(manager.acquire_due())
        assert (first.status, first.vod_id, first.keep_from, first.keep_until) == (
            "downloaded", "777p1", None, LIVE_PART_SECONDS - LIVE_PART_KEEP_LEAD)
        assert downloads[-1] == ("https://www.twitch.tv/videos/777", (0.0, LIVE_PART_SECONDS), "777p1")
        # The pipeline records it under the acquisition's ids: the stream's, not the job's "s1#p1".
        manager.record_automation(first.stream_id, first.vod_id, "completed")
        assert manager.pending_jobs == 0

        clock[0] += timedelta(seconds=LIVE_PART_SECONDS)
        manager.process_cycle(cycle)
        [second] = list(manager.acquire_due())
        assert second.vod_id == "777p2"
        assert downloads[-1][1] == (LIVE_PART_SECONDS - LIVE_PART_LEAD, 2 * LIVE_PART_SECONDS)  # with the lead-in
        assert (second.keep_from, second.keep_until) == (
            LIVE_PART_SECONDS - LIVE_PART_KEEP_LEAD, 2 * LIVE_PART_SECONDS - LIVE_PART_KEEP_LEAD)
        manager.record_automation(second.stream_id, second.vod_id, "completed")

        # The stream ends: only what follows the last part is left, never the whole VOD again.
        assert [r.status for r in manager.process_cycle(MonitoringCycle(ended_streams=(live(),)))] == ["queued_part"]
        [last] = list(manager.acquire_due())
        assert last.vod_id == "777p3" and downloads[-1][1] == (2 * LIVE_PART_SECONDS - LIVE_PART_LEAD, None)
        assert (last.keep_from, last.keep_until) == (2 * LIVE_PART_SECONDS - LIVE_PART_KEEP_LEAD, None)
        manager.record_automation(last.stream_id, last.vod_id, "completed")
        assert manager.pending_jobs == 0
        assert [r.status for r in manager.process_cycle(MonitoringCycle(ended_streams=(live(),)))] == ["already_processed"]

        # The parts survive a restart.
        restarted = TwitchVODAcquisitionManager(api_client=client, input_dir=root / "in", state_path=root / "s.json",
                                                downloader=download, clock=lambda: clock[0], live_parts=True)
        assert restarted.pending_jobs == 0


def test_without_live_clipping_a_stream_waits_for_its_end_as_before():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manager = TwitchVODAcquisitionManager(api_client=Mock(), input_dir=root / "in", state_path=root / "s.json",
                                              clock=lambda: STARTED + timedelta(hours=10))
        assert manager.process_cycle(MonitoringCycle(streams=(live(),))) == ()
        assert [r.status for r in manager.process_cycle(MonitoringCycle(ended_streams=(live(),)))] == ["queued"]
        assert list(manager._jobs) == ["s1"]


def test_a_live_part_past_the_end_of_a_shorter_vod_takes_its_last_stretch():
    """A stream's cuts are not in its VOD: a part cut on the wall clock can start past the VOD's end."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        clock = [STARTED + timedelta(seconds=LIVE_PART_SECONDS + LIVE_LAG_SECONDS)]
        downloads = []

        def download(url, folder, section=None, name=None):
            downloads.append(section)
            path = folder / f"{name}_audio.mp4"
            path.write_bytes(b"audio")
            return path

        client = Mock()
        client.find_vod_for_stream.return_value = TwitchVOD("777", "s1", "b1", "title")
        client.fetch_vod.return_value = TwitchVOD("777", "s1", "b1", "title", seconds=LIVE_PART_SECONDS / 2)
        manager = TwitchVODAcquisitionManager(api_client=client, input_dir=root / "in", state_path=root / "s.json",
                                              downloader=download, clock=lambda: clock[0], live_parts=True)
        manager.process_cycle(MonitoringCycle(streams=(live(),)))
        [first] = list(manager.acquire_due())
        assert downloads[-1] == (0.0, LIVE_PART_SECONDS)  # starts inside the VOD: kept as cut
        manager.record_automation(first.stream_id, first.vod_id, "completed")

        clock[0] += timedelta(seconds=LIVE_PART_SECONDS)
        client.fetch_vod.return_value = TwitchVOD("777", "s1", "b1", "title", seconds=0.75 * LIVE_PART_SECONDS)  # still short of 2 h
        manager.process_cycle(MonitoringCycle(streams=(live(),)))
        [second] = list(manager.acquire_due())
        assert second.status == "downloaded"
        assert downloads[-1] == (0.0, None)  # the VOD's last 2 hours (here all of it), not 2-4 h


def test_helix_durations_are_read_in_seconds():
    from twitch_auto_clipper.twitch_api import _duration_seconds

    assert _duration_seconds("8h36m37s") == 30997.0
    assert _duration_seconds("59s") == 59.0
    assert _duration_seconds("") is None and _duration_seconds("bad") is None


def test_a_failed_part_download_names_the_error_and_leaves_no_cache(monkeypatch):
    import os
    import subprocess

    import pytest

    from twitch_auto_clipper import twitch, twitch_chat

    seen = []

    def run(command, **_):
        cache = command[command.index("--temp-path") + 1]
        seen.append(cache)
        assert os.path.isdir(cache)
        raise subprocess.CalledProcessError(1, command, stderr="Unhandled exception.\n ---> System.Exception: Failed to finalize video.\n   at X")

    monkeypatch.setattr(twitch_chat, "find_twitch_downloader_cli", lambda: "cli.exe")
    monkeypatch.setattr(twitch.subprocess, "run", run)
    with tempfile.TemporaryDirectory() as directory:
        with pytest.raises(twitch.TwitchDownloadError, match="Failed to finalize video"):
            twitch._download_section("777", Path(directory), (0.0, 60.0), "777p1", None)
    assert seen and not os.path.exists(seen[0])
