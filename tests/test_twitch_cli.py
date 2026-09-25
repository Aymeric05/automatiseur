import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from twitch_auto_clipper.cli import main
from twitch_auto_clipper.twitch_api import LiveStream
from twitch_auto_clipper.twitch_monitor import MonitoredStream, MonitoringCycle
from twitch_auto_clipper.vod_acquisition import VODAcquisitionResult, VODMonitoringCycle


class TwitchCliTests(unittest.TestCase):
    @patch("twitch_auto_clipper.cli.VODProcessingPipeline.process")
    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.poll_once")
    def test_monitor_once_starts_processing_for_acquired_vod(
        self, poll_once, process_vod
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            video_path = Path(temporary_directory) / "vod-1.mp4"
            video_path.write_bytes(b"video")
            acquisition = VODAcquisitionResult(
                stream_id="stream-1",
                clip_budget=5,
                status="downloaded",
                broadcaster_id="broadcaster-1",
                broadcaster_login="login",
                broadcaster_name="Name",
                vod_id="vod-1",
                downloaded_path=video_path,
            )
            poll_once.return_value = VODMonitoringCycle(
                MonitoringCycle(), (acquisition,)
            )
            arguments = ["twitch_auto_clipper", "--monitor-twitch-once"]

            with patch.object(sys, "argv", arguments), patch("builtins.print"):
                result = main()

        self.assertEqual(result, 0)
        process_vod.assert_called_once_with(acquisition)

    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.poll_once")
    def test_monitor_twitch_once_prints_cycle_and_returns_success(self, poll_once) -> None:
        poll_once.return_value = VODMonitoringCycle(
            MonitoringCycle(
                newly_discovered=(
                    MonitoredStream(
                        LiveStream(
                            "stream-1", "broadcaster-1", "login", "Name", 1234,
                            "Title", "Game", "en", "2026-09-25T12:00:00Z",
                        ),
                        0,
                    ),
                )
            )
        )
        arguments = ["twitch_auto_clipper", "--monitor-twitch-once"]

        with patch.object(sys, "argv", arguments), patch("builtins.print") as print_output:
            result = main()

        self.assertEqual(result, 0)
        poll_once.assert_called_once()
        print_output.assert_called_once_with(
            "Nouveau stream : Name (@login) - 1234 viewers - budget : 0 clips",
            file=sys.stdout,
        )

    @patch("twitch_auto_clipper.cli.TwitchAPIClient.fetch_english_streams")
    def test_list_twitch_streams_prints_highest_viewed_results(self, fetch_streams) -> None:
        fetch_streams.return_value = [
            LiveStream(
                "stream-1", "broadcaster-1", "login", "Name", 1234,
                "Title", "Game", "en", "2026-09-25T12:00:00Z",
            )
        ]
        arguments = ["twitch_auto_clipper", "--list-twitch-streams", "--stream-limit", "5"]

        with patch.object(sys, "argv", arguments), patch("builtins.print") as print_output:
            result = main()

        self.assertEqual(result, 0)
        fetch_streams.assert_called_once_with(limit=5)
        print_output.assert_called_once_with("    1234 viewers | Name (@login) | Game | Title")


if __name__ == "__main__":
    unittest.main()