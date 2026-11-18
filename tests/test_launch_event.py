"""GTA 6 launch week: boosted until launch_event.END, then exactly as before."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from twitch_auto_clipper import launch_event
from twitch_auto_clipper.shorts_metadata import build_short_metadata
from twitch_auto_clipper.twitch_api import LiveStream
from twitch_auto_clipper.twitch_monitor import MonitoredStream, MonitoringCycle, TwitchStreamMonitor
from twitch_auto_clipper.vod_acquisition import TwitchVODAcquisitionManager

DURING = launch_event.END - timedelta(days=3)
AFTER = launch_event.END + timedelta(minutes=1)


def stream(stream_id: str, viewers: int, game: str) -> LiveStream:
    return LiveStream(stream_id=stream_id, broadcaster_id=f"b-{stream_id}", broadcaster_login=stream_id,
                      broadcaster_name=stream_id, viewer_count=viewers, title="t", game_name=game,
                      language="en", started_at="2026-11-19T00:00:00Z")


def test_only_gta_6_is_recognised_and_only_during_the_week():
    for name in ("Grand Theft Auto VI", "grand theft auto 6", "GTA VI", "GTA 6"):
        assert launch_event.boosted(name, DURING), name
        assert not launch_event.boosted(name, AFTER), name
    for name in ("Grand Theft Auto V", "Grand Theft Auto: Vice City", "Grand Theft Auto Vice City", "GTA V", "", None):
        assert not launch_event.boosted(name, DURING), name


def test_monitor_follows_smaller_gta_6_streams_during_the_week_only():
    for end, expected_minimum, expected in ((datetime(2100, 1, 1, tzinfo=timezone.utc), 1000, {"gta6"}),
                                            (datetime(2000, 1, 1, tzinfo=timezone.utc), 5000, set())):
        client = Mock()
        client.fetch_english_streams.return_value = [stream("gta6", 2000, "Grand Theft Auto VI"),
                                                     stream("other", 2000, "Fortnite")]
        with tempfile.TemporaryDirectory() as directory, patch.object(launch_event, "END", end):
            cycle = TwitchStreamMonitor(client=client, state_path=Path(directory) / "s.json").poll_once()
        client.fetch_english_streams.assert_called_once_with(min_viewers=expected_minimum)
        assert {m.stream.stream_id for m in cycle.streams} == expected


def test_queue_puts_gta_6_first_with_the_top_list_treatment_then_returns_to_normal():
    with tempfile.TemporaryDirectory() as directory:
        clock = [DURING]
        manager = TwitchVODAcquisitionManager(api_client=Mock(), input_dir=Path(directory) / "in",
                                              state_path=Path(directory) / "s.json", clock=lambda: clock[0])
        manager.process_cycle(MonitoringCycle(ended_streams=(
            MonitoredStream(stream("gta6", 1500, "Grand Theft Auto VI"), 5),
            MonitoredStream(stream("big", 60_000, "Fortnite"), 15),
        )))
        jobs = manager._jobs
        ranked = lambda: [s for s, _ in sorted(jobs.items(), key=lambda e: manager._priority(*e))]
        assert ranked() == ["gta6", "big"]
        assert manager._budget("gta6", 5, "Grand Theft Auto VI") == 25
        assert manager._max_age(jobs["gta6"]) == timedelta(days=3)
        clock[0] = AFTER  # exactly the behaviour before the launch week
        assert ranked() == ["big", "gta6"]
        assert manager._budget("gta6", 5, "Grand Theft Auto VI") == 5
        assert manager._max_age(jobs["gta6"]) == timedelta(hours=48)


def test_titles_and_hashtags_name_gta_6_during_the_week_only():
    options = dict(broadcaster_name="Kai", broadcaster_login="kai", vod_id="1",
                   segments=[{"start": 0, "end": 5, "text": "No way he did that."}], clip_start=0, clip_end=5,
                   game_name="Grand Theft Auto VI", title="Kai Steals A Police Car")
    with patch.object(launch_event, "END", datetime(2100, 1, 1, tzinfo=timezone.utc)):
        during = build_short_metadata(**options)
        already = build_short_metadata(**{**options, "title": "Kai's First GTA 6 Heist"})
    with patch.object(launch_event, "END", datetime(2000, 1, 1, tzinfo=timezone.utc)):
        after = build_short_metadata(**options)
    assert during.title.endswith("(GTA 6)") and "#gta6" in during.description
    assert not already.title.endswith("(GTA 6)")  # never twice
    assert "GTA 6" not in after.title and "#gta6" not in after.description
