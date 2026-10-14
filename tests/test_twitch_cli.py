import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from twitch_auto_clipper import cli
from twitch_auto_clipper.cli import main
from twitch_auto_clipper.twitch_api import LiveStream
from twitch_auto_clipper.twitch_monitor import MonitoredStream, MonitoringCycle
from twitch_auto_clipper.vod_acquisition import VODAcquisitionResult, VODMonitoringCycle


class RotatingLogTests(unittest.TestCase):
    def test_log_never_grows_past_its_limit_and_keeps_the_previous_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.log"
            log = cli.RotatingLog(path, max_bytes=100)
            for index in range(30):
                print(f"ligne {index} \U0001F525", file=log)
            log._file.close()
            old = path.with_name("monitor.old.log")
            self.assertTrue(old.is_file())
            self.assertLessEqual(path.stat().st_size, 100 + 20)
            self.assertIn("ligne 29", path.read_text(encoding="utf-8"))


class TwitchCliTests(unittest.TestCase):
    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.record_automation", return_value="done")
    @patch("twitch_auto_clipper.cli.VODAutomationPipeline.run")
    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.acquire_due")
    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.poll_once")
    def test_monitor_once_processes_the_due_vod_jobs(
        self, poll_once, acquire_due, automation_run, record
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_path = Path(temporary_directory) / "vod-1_audio.mp4"
            audio_path.write_bytes(b"audio")
            acquisition = VODAcquisitionResult(
                stream_id="stream-1",
                clip_budget=5,
                status="downloaded",
                broadcaster_id="broadcaster-1",
                broadcaster_login="login",
                broadcaster_name="Name",
                vod_id="vod-1",
                downloaded_path=audio_path,
            )
            poll_once.return_value = VODMonitoringCycle(MonitoringCycle())
            acquire_due.return_value = iter([acquisition])
            automation_run.return_value = Mock(
                status="completed", processing=None, selection=None, shorts=None,
                metadata=(), message=None, vod_id="vod-1", retry_at=None,
            )
            arguments = ["twitch_auto_clipper", "--monitor-twitch-once"]

            with patch.object(sys, "argv", arguments), patch("builtins.print"):
                result = main()

        self.assertEqual(result, 0)
        automation_run.assert_called_once_with(acquisition)
        record.assert_called_once_with(
            "stream-1", "vod-1", "completed", retry_at=None, error=None
        )

    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.poll_once")
    def test_monitor_twitch_once_prints_concise_cycle_and_returns_success(self, poll_once) -> None:
        eligible = MonitoredStream(
            LiveStream(
                "stream-1", "broadcaster-1", "login", "Name", 12_345,
                "Title", "Game", "en", "2026-09-25T12:00:00Z",
            ),
            5,
        )
        poll_once.return_value = VODMonitoringCycle(
            MonitoringCycle(
                streams=(eligible,),
                newly_discovered=(eligible,),
                scanned_stream_count=5_000,
                duration_seconds=4.2,
            )
        )
        arguments = ["twitch_auto_clipper", "--monitor-twitch-once"]

        with patch.object(sys, "argv", arguments), patch("builtins.print") as print_output:
            result = main()

        self.assertEqual(result, 0)
        poll_once.assert_called_once()
        lines = [call.args[0] for call in print_output.call_args_list]
        self.assertEqual(lines, [
            "Cycle Twitch : 5000 streams anglais parcourus, 1 avec budget > 0, 1 suivis (4.2s)",
            "Budgets : 5 clips x1",
            "Nouveau stream : Name (@login) - 12345 viewers - budget : 5 clips",
        ])

    @patch("twitch_auto_clipper.cli.confirm_upload_rights", return_value=False)
    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.poll_once")
    def test_auto_upload_requires_rights_confirmation_before_monitoring(
        self, poll_once, confirm_rights
    ) -> None:
        arguments = ["twitch_auto_clipper", "--monitor-twitch-once", "--auto-upload-youtube"]

        with patch.object(sys, "argv", arguments), patch("builtins.print"):
            result = main()

        self.assertEqual(result, 1)
        confirm_rights.assert_called_once()
        poll_once.assert_not_called()

    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.run")
    def test_monitor_twitch_passes_max_cycles(self, run) -> None:
        arguments = ["twitch_auto_clipper", "--monitor-twitch", "--max-cycles", "2",
                     "--monitor-interval", "1"]
        with patch.object(sys, "argv", arguments), patch("builtins.print"):
            result = main()
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.kwargs["max_cycles"], 2)

    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.run", side_effect=KeyboardInterrupt)
    def test_ctrl_c_stops_cleanly_and_keeps_queued_vods(self, run) -> None:
        state = cli.DATA_DIR / "output" / "twitch_vod_state.json"
        state.parent.mkdir(parents=True)
        state.write_text('{"processed_streams": {}, "processed_vod_ids": [], "jobs": {}}', encoding="utf-8")
        short = cli.DATA_DIR / "output" / "vod-1_12.0-30.0_short.mp4"
        short.write_bytes(b"unpublished short")
        arguments = ["twitch_auto_clipper", "--monitor-twitch"]
        with patch.object(sys, "argv", arguments), patch("builtins.print"):
            result = main()
        self.assertEqual(result, 130)
        self.assertTrue(short.is_file())  # nothing deleted on interruption
        self.assertTrue(state.is_file())

    def test_a_second_monitor_on_the_same_data_is_refused(self) -> None:
        lock = cli.acquire_instance_lock(cli.DATA_DIR / "output" / ".monitor.lock")
        self.assertIsNotNone(lock)
        try:
            self.assertIsNone(cli.acquire_instance_lock(cli.DATA_DIR / "output" / ".monitor.lock"))
            with patch.object(sys, "argv", ["twitch_auto_clipper", "--monitor-twitch-once"]), \
                    patch("builtins.print"), \
                    patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.poll_once") as poll_once:
                self.assertEqual(main(), 1)
            poll_once.assert_not_called()
        finally:
            lock.close()
        released = cli.acquire_instance_lock(cli.DATA_DIR / "output" / ".monitor.lock")
        self.assertIsNotNone(released)  # released as soon as its holder closes or exits
        released.close()

    def test_invalid_daily_upload_limit_is_rejected(self) -> None:
        arguments = ["twitch_auto_clipper", "--monitor-twitch-once"]
        with patch.dict(os.environ, {"YOUTUBE_MAX_UPLOADS_PER_DAY": "zero"}), \
                patch.object(sys, "argv", arguments), patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                main()

    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.acquire_due", return_value=iter([]))
    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.poll_once")
    @patch("twitch_auto_clipper.cli.authenticate_youtube")
    def test_yes_starts_auto_upload_without_keyboard(self, authenticate, poll_once, acquire_due) -> None:
        poll_once.return_value = VODMonitoringCycle(MonitoringCycle())
        arguments = ["twitch_auto_clipper", "--monitor-twitch-once", "--auto-upload-youtube", "--yes"]
        with patch.dict(os.environ, {"YOUTUBE_PRIVACY_POLICY_URL": "https://example.test/privacy"}), \
                patch.object(sys, "argv", arguments), patch("builtins.print"), \
                patch("builtins.input", side_effect=AssertionError("no keyboard at start-up")):
            result = main()
        self.assertEqual(result, 0)
        authenticate.assert_called_once()
        poll_once.assert_called_once()

    @patch("twitch_auto_clipper.cli.TwitchVODAcquisitionManager.poll_once")
    @patch("twitch_auto_clipper.cli.authenticate_youtube")
    @patch("twitch_auto_clipper.cli.confirm_privacy_policy", return_value=True)
    @patch("twitch_auto_clipper.cli.confirm_upload_rights", return_value=True)
    def test_auto_upload_authenticates_once_before_monitoring(
        self, rights, policy, authenticate, poll_once
    ) -> None:
        from twitch_auto_clipper.youtube import YouTubeUploadError

        authenticate.side_effect = YouTubeUploadError("token invalide")
        arguments = ["twitch_auto_clipper", "--monitor-twitch-once", "--auto-upload-youtube"]
        with patch.object(sys, "argv", arguments), patch("builtins.print"):
            result = main()
        self.assertEqual(result, 1)
        authenticate.assert_called_once()
        poll_once.assert_not_called()

    def test_check_config_reports_yes_no_without_secret_values(self) -> None:
        secret = "super-secret-value-123"
        env = {"TWITCH_CLIENT_ID": secret, "TWITCH_CLIENT_SECRET": "", "GEMINI_API_KEY": secret}
        arguments = ["twitch_auto_clipper", "--check-config"]
        with patch.dict("os.environ", env, clear=True), patch.object(sys, "argv", arguments), \
                patch("builtins.print") as print_output:
            result = main()
        output = "\n".join(call.args[0] for call in print_output.call_args_list)
        self.assertEqual(result, 1)  # TWITCH_CLIENT_SECRET missing
        self.assertNotIn(secret, output)
        self.assertIn("oui  TWITCH_CLIENT_ID", output)
        self.assertIn("NON  TWITCH_CLIENT_SECRET", output)

    def test_check_config_reads_the_env_file(self) -> None:
        arguments = ["twitch_auto_clipper", "--check-config"]
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_bytes(b"YOUTUBE_PRIVACY_POLICY_URL=https://example.test/privacy.html\r\n")
            with patch("twitch_auto_clipper.cli.ENV_FILE", env_file), \
                    patch.dict("os.environ", {}, clear=True), patch.object(sys, "argv", arguments), \
                    patch("builtins.print") as print_output:
                main()
        output = "\n".join(call.args[0] for call in print_output.call_args_list)
        self.assertIn("oui  YOUTUBE_PRIVACY_POLICY_URL", output)

    def test_env_file_parsing_never_overrides_real_environment_variables(self) -> None:
        from twitch_auto_clipper.cli import load_env_file

        content = (
            "# comment\n\n"
            " PLAIN = value with spaces \n"
            'QUOTED="https://x.test/a=b#frag"\n'
            "ALREADY_SET=from-file\n"
            "line without separator\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            load_env_file(Path(directory) / "missing.env")  # no file: nothing to do
            for encoding in ("utf-8", "utf-8-sig", "utf-16"):  # plain, BOM, PowerShell 5.1 ">"
                env_file = Path(directory) / f"{encoding}.env"
                env_file.write_text(content, encoding=encoding)  # CRLF line endings on Windows
                with self.subTest(encoding=encoding), \
                        patch.dict("os.environ", {"ALREADY_SET": "real"}, clear=True):
                    load_env_file(env_file)
                    self.assertEqual(set(os.environ), {"ALREADY_SET", "PLAIN", "QUOTED"})
                    self.assertEqual(os.environ["PLAIN"], "value with spaces")
                    self.assertEqual(os.environ["QUOTED"], "https://x.test/a=b#frag")
                    self.assertEqual(os.environ["ALREADY_SET"], "real")

    def test_process_vod_refuses_any_upload_option(self) -> None:
        for extra in ("--auto-upload-youtube", "--upload-youtube"):
            arguments = ["twitch_auto_clipper", "--process-vod", "123", extra]
            with patch.object(sys, "argv", arguments), patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    main()

    @patch("twitch_auto_clipper.cli.TwitchAPIClient.fetch_live_streams_by_user_ids", return_value={})
    @patch("twitch_auto_clipper.cli.VODAutomationPipeline")
    @patch("twitch_auto_clipper.cli.download_twitch_vod")
    @patch("twitch_auto_clipper.cli.TwitchAPIClient.fetch_vod")
    def test_process_vod_test_mode_downloads_only_the_audio_of_the_extract_without_uploader(
        self, fetch_vod, download, pipeline_class, live_lookup
    ) -> None:
        from twitch_auto_clipper.twitch_api import TwitchVOD

        fetch_vod.return_value = TwitchVOD("123", "s1", "b1", "Title", "login", "Name")
        download.return_value = cli.DATA_DIR / "test" / "input" / "123_audio.mp4"
        pipeline_class.return_value.run.return_value = Mock(
            status="completed", processing=None, selection=None, shorts=None,
            metadata=(), message=None, vod_id="123",
        )
        arguments = ["twitch_auto_clipper", "--process-vod",
                     "https://www.twitch.tv/videos/123", "--clip-budget", "3", "--test-minutes", "10"]
        with patch.object(sys, "argv", arguments), patch("builtins.print"), \
                patch.object(Path, "is_file", return_value=False):
            result = main()

        self.assertEqual(result, 0)
        download.assert_called_once_with(
            "https://www.twitch.tv/videos/123", cli.DATA_DIR / "test" / "input",
            max_seconds=600, audio_only=True,
        )
        self.assertNotIn("uploader", pipeline_class.call_args.kwargs)  # never publishes
        self.assertEqual(pipeline_class.call_args.kwargs["output_dir"], cli.DATA_DIR / "test" / "output")
        # The Shorts read their seconds of video from Twitch, not from a local file.
        self.assertIs(pipeline_class.call_args.kwargs["video_source"], cli._twitch_video)
        chat_downloader = pipeline_class.call_args.kwargs["processing_pipeline"].chat_downloader
        self.assertEqual(chat_downloader.keywords, {"end_seconds": 600})  # only the extract's chat
        acquisition = pipeline_class.return_value.run.call_args.args[0]
        self.assertEqual((acquisition.vod_id, acquisition.clip_budget, acquisition.broadcaster_login),
                         ("123", 3, "login"))

    @patch("twitch_auto_clipper.cli.TwitchAPIClient.fetch_live_streams_by_user_ids", return_value={})
    @patch("twitch_auto_clipper.cli.VODAutomationPipeline")
    @patch("twitch_auto_clipper.cli.download_twitch_vod")
    @patch("twitch_auto_clipper.cli.TwitchAPIClient.fetch_vod")
    def test_process_vod_reuses_an_existing_download(
        self, fetch_vod, download, pipeline_class, live_lookup
    ) -> None:
        from twitch_auto_clipper.twitch_api import TwitchVOD

        audio = cli.DATA_DIR / "input" / "123_audio.mp4"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"audio")
        fetch_vod.return_value = TwitchVOD("123", "s1", "b1", "Title", "login", "Name")
        pipeline_class.return_value.run.return_value = Mock(
            status="partial", processing=None, selection=None, shorts=None,
            metadata=(), message="x", vod_id="123",
        )
        arguments = ["twitch_auto_clipper", "--process-vod", "123"]
        with patch.object(sys, "argv", arguments), patch("builtins.print"):
            result = main()
        self.assertEqual(result, 1)  # partial is reported as a failure
        download.assert_not_called()
        self.assertEqual(pipeline_class.return_value.run.call_args.args[0].downloaded_path, audio)

    def _process_vod_with_live(self, vod_stream_id, live):
        """Run --process-vod on an already downloaded VOD with a given live-check result."""
        from twitch_auto_clipper.twitch_api import LiveStream, TwitchVOD

        if isinstance(live, str):
            live = {"b1": LiveStream(live, "b1", "login", "Name", 9_000, "T", "G", "en", "x")}
        lookup = {"side_effect": live} if isinstance(live, Exception) else {"return_value": live}
        with patch("twitch_auto_clipper.cli.TwitchAPIClient.fetch_vod",
                   return_value=TwitchVOD("123", vod_stream_id, "b1", "Title", "login", "Name")), \
                patch("twitch_auto_clipper.cli.TwitchAPIClient.fetch_live_streams_by_user_ids", **lookup), \
                patch("twitch_auto_clipper.cli.download_twitch_vod") as download, \
                patch("twitch_auto_clipper.cli.VODAutomationPipeline") as pipeline_class, \
                patch.object(sys, "argv", ["twitch_auto_clipper", "--process-vod", "123"]), \
                patch("builtins.print"), \
                patch("twitch_auto_clipper.cli.find_downloaded_audio", return_value=Path("123_audio.mp4")):
            pipeline_class.return_value.run.return_value = Mock(
                status="completed", processing=None, selection=None, shorts=None,
                metadata=(), message=None, vod_id="123",
            )
            return main(), pipeline_class.return_value.run.called, download.called

    def test_process_vod_refuses_a_vod_whose_stream_is_still_live(self) -> None:
        self.assertEqual(self._process_vod_with_live("s1", "s1"), (1, False, False))

    def test_process_vod_refuses_unknown_vod_stream_id_while_broadcaster_is_live(self) -> None:
        self.assertEqual(self._process_vod_with_live("", "s-any"), (1, False, False))

    def test_process_vod_refuses_when_the_live_check_fails(self) -> None:
        from twitch_auto_clipper.twitch_api import TwitchAPIError

        self.assertEqual(self._process_vod_with_live("s1", TwitchAPIError("helix down")), (1, False, False))

    def test_process_vod_accepts_a_finished_vod(self) -> None:
        self.assertEqual(self._process_vod_with_live("s1", {}), (0, True, False))  # offline
        self.assertEqual(self._process_vod_with_live("s1", "s2"), (0, True, False))  # new live session

    def test_max_cycles_must_be_positive(self) -> None:
        arguments = ["twitch_auto_clipper", "--monitor-twitch", "--max-cycles", "0"]
        with patch.object(sys, "argv", arguments), patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                main()

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