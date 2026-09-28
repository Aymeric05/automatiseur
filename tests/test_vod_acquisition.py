from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from twitch_auto_clipper.twitch_api import LiveStream, TwitchAPIError, TwitchVOD
from twitch_auto_clipper.twitch_monitor import MonitoringCycle, MonitoredStream
from twitch_auto_clipper.vod_acquisition import TwitchVODAcquisitionManager


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


class VODAcquisitionTests(unittest.TestCase):
    def make_manager(self, temporary_directory, client, downloader=None):
        root = Path(temporary_directory)
        return TwitchVODAcquisitionManager(
            api_client=client,
            input_dir=root / "input",
            state_path=root / "state" / "vods.json",
            downloader=downloader,
        )

    def test_ended_stream_resolves_and_downloads_vod_once(self) -> None:
        client = Mock()
        client.find_vod_for_stream.return_value = vod()
        download = Mock(return_value=Path("data/input/vod-1.mp4"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = self.make_manager(temporary_directory, client, download)
            cycle = MonitoringCycle(ended_streams=(monitored_stream(),))

            first = manager.process_cycle(cycle)
            second = manager.process_cycle(cycle)

            self.assertEqual(first[0].status, "downloaded")
            self.assertEqual(first[0].clip_budget, 5)
            self.assertEqual(first[0].vod_id, "vod-1")
            self.assertEqual(second[0].status, "already_processed")
            client.find_vod_for_stream.assert_called_once_with("broadcaster-1", "stream-1")
            download.assert_called_once_with(
                "https://www.twitch.tv/videos/vod-1",
                Path(temporary_directory) / "input",
            )

            state = (Path(temporary_directory) / "state" / "vods.json").read_text(
                encoding="utf-8"
            )
            self.assertIn('"stream-1": "vod-1"', state)
            self.assertIn('"vod-1"', state)

    def test_unavailable_vod_is_retried_on_a_later_cycle(self) -> None:
        client = Mock()
        client.find_vod_for_stream.side_effect = [None, vod()]
        download = Mock(return_value=Path("data/input/vod-1.mp4"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = self.make_manager(temporary_directory, client, download)
            end_cycle = MonitoringCycle(ended_streams=(monitored_stream(),))

            first = manager.process_cycle(end_cycle)
            second = manager.process_cycle(MonitoringCycle())

        self.assertEqual(first[0].status, "vod_not_available")
        self.assertEqual(second[0].status, "downloaded")
        self.assertEqual(client.find_vod_for_stream.call_count, 2)
        download.assert_called_once()

    def test_zero_budget_skips_vod_lookup_and_download(self) -> None:
        client = Mock()
        download = Mock()
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = self.make_manager(temporary_directory, client, download)
            result = manager.process_cycle(
                MonitoringCycle(ended_streams=(monitored_stream(budget=0),))
            )

        self.assertEqual(result[0].status, "skipped_zero_budget")
        client.find_vod_for_stream.assert_not_called()
        download.assert_not_called()

    def test_api_error_does_not_drop_pending_stream(self) -> None:
        client = Mock()
        client.find_vod_for_stream.side_effect = [TwitchAPIError("temporary"), vod()]
        download = Mock(return_value=Path("data/input/vod-1.mp4"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = self.make_manager(temporary_directory, client, download)
            first = manager.process_cycle(
                MonitoringCycle(ended_streams=(monitored_stream(),))
            )
            second = manager.process_cycle(MonitoringCycle())

        self.assertEqual(first[0].status, "error")
        self.assertEqual(second[0].status, "downloaded")

    def test_persisted_state_prevents_download_after_restart(self) -> None:
        client = Mock()
        download = Mock()
        with tempfile.TemporaryDirectory() as temporary_directory:
            first_manager = self.make_manager(temporary_directory, client, download)
            first_manager._remember_processed("stream-1", "vod-1")
            restarted_manager = self.make_manager(temporary_directory, client, download)

            result = restarted_manager.process_cycle(
                MonitoringCycle(ended_streams=(monitored_stream(),))
            )

        self.assertEqual(result[0].status, "already_processed")
        client.find_vod_for_stream.assert_not_called()
        download.assert_not_called()

    def test_known_vod_id_keeps_its_downloaded_path_for_processing(self) -> None:
        client = Mock()
        client.find_vod_for_stream.return_value = vod()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "input").mkdir()
            (root / "input" / "vod-1.mp4").write_bytes(b"video")
            (root / "state").mkdir()
            (root / "state" / "vods.json").write_text(
                '{"processed_streams": {}, "processed_vod_ids": ["vod-1"]}', encoding="utf-8"
            )
            manager = self.make_manager(temporary_directory, client)

            result = manager.process_cycle(MonitoringCycle(ended_streams=(monitored_stream(),)))

            self.assertEqual(result[0].status, "already_processed")
            self.assertEqual(result[0].downloaded_path, root / "input" / "vod-1.mp4")

    def test_existing_vod_file_is_recorded_without_downloading(self) -> None:
        client = Mock()
        client.find_vod_for_stream.return_value = vod()
        download = Mock()
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = self.make_manager(temporary_directory, client, download)
            existing_path = Path(temporary_directory) / "input" / "vod-1.mp4"
            existing_path.parent.mkdir(parents=True)
            existing_path.write_bytes(b"already here")

            result = manager.process_cycle(
                MonitoringCycle(ended_streams=(monitored_stream(),))
            )

        self.assertEqual(result[0].status, "already_downloaded")
        self.assertEqual(result[0].downloaded_path, existing_path)
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()