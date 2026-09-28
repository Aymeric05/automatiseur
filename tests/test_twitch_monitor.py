import unittest
from unittest.mock import Mock

from twitch_auto_clipper.twitch_api import LiveStream, TwitchAPIError
from twitch_auto_clipper.twitch_monitor import TwitchStreamMonitor


def make_stream(stream_id: str, viewers: int, language: str = "en") -> LiveStream:
    return LiveStream(
        stream_id=stream_id,
        broadcaster_id=f"broadcaster-{stream_id}",
        broadcaster_login=f"login-{stream_id}",
        broadcaster_name=f"Broadcaster {stream_id}",
        viewer_count=viewers,
        title=f"Title {stream_id}",
        game_name="Game",
        language=language,
        started_at="2026-09-25T12:00:00Z",
    )


class TwitchStreamMonitorTests(unittest.TestCase):
    def test_polling_reports_new_streams_then_only_viewer_count_changes(self) -> None:
        client = Mock()
        client.fetch_english_streams.side_effect = [
            [make_stream("one", 50_000), make_stream("two", 10_000)],
            [make_stream("one", 50_000), make_stream("two", 10_000)],
            [make_stream("one", 20_000), make_stream("two", 10_000)],
        ]
        monitor = TwitchStreamMonitor(client=client)

        first = monitor.poll_once()
        second = monitor.poll_once()
        third = monitor.poll_once()

        self.assertEqual([s.stream.stream_id for s in first.newly_discovered], ["one", "two"])
        self.assertEqual([s.clip_budget for s in first.streams], [15, 5])
        self.assertEqual(second.newly_discovered, ())
        self.assertEqual(second.viewer_count_changes, ())
        self.assertEqual(len(third.viewer_count_changes), 1)
        self.assertEqual(third.viewer_count_changes[0].stream.stream.stream_id, "one")
        self.assertEqual(third.viewer_count_changes[0].previous_viewer_count, 50_000)
        self.assertEqual(third.viewer_count_changes[0].stream.clip_budget, 10)
        self.assertEqual(client.fetch_english_streams.call_count, 3)

    def test_non_english_streams_are_filtered(self) -> None:
        client = Mock()
        client.fetch_english_streams.return_value = [
            make_stream("english", 100_000),
            make_stream("french", 100_000, language="fr"),
        ]

        cycle = TwitchStreamMonitor(client=client).poll_once()

        self.assertEqual([s.stream.stream_id for s in cycle.streams], ["english"])
        self.assertEqual([s.stream.stream_id for s in cycle.newly_discovered], ["english"])

    def test_api_error_is_reported_and_next_poll_continues(self) -> None:
        client = Mock()
        client.fetch_english_streams.side_effect = [
            TwitchAPIError("temporary network failure"),
            [make_stream("one", 5_000)],
        ]
        monitor = TwitchStreamMonitor(client=client)

        failed_cycle = monitor.poll_once()
        recovered_cycle = monitor.poll_once()

        self.assertEqual(failed_cycle.error, "temporary network failure")
        self.assertEqual(failed_cycle.streams, ())
        self.assertEqual(len(recovered_cycle.newly_discovered), 1)
        self.assertIsNone(recovered_cycle.error)

    @staticmethod
    def _ended_per_poll(snapshots, confirmations=3, status_checks=None):
        """Each poll lists `snapshots[i]`; direct checks return offline unless given."""
        client = Mock()
        client.fetch_english_streams.side_effect = snapshots
        client.fetch_live_streams_by_user_ids.side_effect = status_checks
        client.fetch_live_streams_by_user_ids.return_value = {}
        monitor = TwitchStreamMonitor(client=client, end_confirmation_polls=confirmations)
        return [
            [s.stream.stream_id for s in monitor.poll_once().ended_streams]
            for _ in snapshots
        ]

    def test_listing_is_limited_to_the_lowest_eligible_viewer_count(self) -> None:
        client = Mock()
        client.fetch_english_streams.return_value = []
        TwitchStreamMonitor(client=client).poll_once()
        client.fetch_english_streams.assert_called_once_with(min_viewers=5_000)

    def test_ineligible_streams_are_not_tracked_nor_status_checked(self) -> None:
        client = Mock()
        client.fetch_english_streams.side_effect = [
            [make_stream("big", 6_000), make_stream("small", 4_900)],
            [make_stream("big", 6_000)],
        ]
        monitor = TwitchStreamMonitor(client=client)
        first = monitor.poll_once()
        second = monitor.poll_once()
        self.assertEqual([s.stream.stream_id for s in first.newly_discovered], ["big"])
        self.assertEqual([s.stream.stream_id for s in first.streams], ["big"])
        self.assertEqual(second.ended_streams, ())
        client.fetch_live_streams_by_user_ids.assert_not_called()

    def test_tracked_stream_below_threshold_but_live_is_kept_and_refreshed(self) -> None:
        client = Mock()
        client.fetch_english_streams.side_effect = [[make_stream("one", 6_000)]] + [[]] * 4
        client.fetch_live_streams_by_user_ids.return_value = {
            "broadcaster-one": make_stream("one", 3_000)
        }
        monitor = TwitchStreamMonitor(client=client)
        monitor.poll_once()
        cycles = [monitor.poll_once() for _ in range(4)]

        self.assertTrue(all(cycle.ended_streams == () for cycle in cycles))
        self.assertEqual([s.stream.viewer_count for s in cycles[-1].streams], [3_000])
        change = cycles[0].viewer_count_changes[0]
        self.assertEqual((change.previous_viewer_count, change.previous_clip_budget), (6_000, 2))
        self.assertEqual(change.stream.clip_budget, 0)
        client.fetch_live_streams_by_user_ids.assert_called_with(["broadcaster-one"])

    def test_new_stream_session_of_same_broadcaster_ends_the_old_one(self) -> None:
        one = [make_stream("one", 6_000)]
        from dataclasses import replace

        restarted = replace(make_stream("one-restarted", 100), broadcaster_id="broadcaster-one")
        other_session = {"broadcaster-one": restarted}
        self.assertEqual(
            self._ended_per_poll([one, [], [], []], status_checks=[other_session] * 3),
            [[], [], [], ["one"]],
        )

    def test_failed_status_check_does_not_count_as_disappearance(self) -> None:
        one = [make_stream("one", 6_000)]
        error = TwitchAPIError("helix /streams?user_id failed")
        self.assertEqual(
            self._ended_per_poll(
                [one, [], [], [], [], []],
                status_checks=[{}, error, {}, error, {}],
            ),
            [[], [], [], [], [], ["one"]],
        )

    def test_same_streams_in_a_different_order_produce_no_events(self) -> None:
        client = Mock()
        a, b = make_stream("a", 9_000), make_stream("b", 8_000)
        client.fetch_english_streams.side_effect = [[a, b], [b, a], [a, b]]
        monitor = TwitchStreamMonitor(client=client)
        monitor.poll_once()
        for cycle in (monitor.poll_once(), monitor.poll_once()):
            self.assertEqual(
                (cycle.newly_discovered, cycle.viewer_count_changes, cycle.ended_streams),
                ((), (), ()),
            )
        client.fetch_live_streams_by_user_ids.assert_not_called()

    @staticmethod
    def _peak_scenario(listing, lookups):
        """Run one poll per listing entry; return the monitor and every cycle."""
        client = Mock()
        client.fetch_english_streams.side_effect = listing
        client.fetch_live_streams_by_user_ids.side_effect = lookups
        monitor = TwitchStreamMonitor(client=client)
        return monitor, [monitor.poll_once() for _ in listing]

    def test_ended_budget_comes_from_the_session_peak(self) -> None:
        live_low = {"broadcaster-one": make_stream("one", 3_000)}
        _, cycles = self._peak_scenario(
            listing=[[make_stream("one", 20_000)], [make_stream("one", 70_000)], [], [], [], [], []],
            lookups=[live_low, live_low, {}, {}, {}],
        )
        self.assertEqual([s.clip_budget for s in cycles[3].streams], [0])  # live, below 5k
        self.assertEqual([s.peak_viewers for s in cycles[3].streams], [70_000])
        self.assertTrue(all(cycle.ended_streams == () for cycle in cycles[:6]))
        ended = cycles[6].ended_streams[0]
        self.assertEqual((ended.stream.viewer_count, ended.peak_viewers), (3_000, 70_000))
        self.assertEqual(ended.clip_budget, 15)  # 70k tier, not the last 3k snapshot

    def test_relaunch_with_new_stream_id_starts_a_fresh_peak(self) -> None:
        from dataclasses import replace

        relaunch = replace(make_stream("two", 6_000), broadcaster_id="broadcaster-one")
        _, cycles = self._peak_scenario(
            listing=[[make_stream("one", 70_000)], [relaunch], [relaunch], [relaunch],
                     [], [], []],
            lookups=[{"broadcaster-one": relaunch}] * 3 + [{}, {}, {}],
        )
        self.assertEqual([(s.stream.stream_id, s.clip_budget) for s in cycles[3].ended_streams],
                         [("one", 15)])
        new_session = cycles[1].newly_discovered[0]
        self.assertEqual((new_session.stream.stream_id, new_session.peak_viewers), ("two", 6_000))
        self.assertEqual([(s.stream.stream_id, s.clip_budget) for s in cycles[6].ended_streams],
                         [("two", 2)])  # 6k peak, not the old 70k session

    def test_api_errors_during_confirmation_keep_the_peak(self) -> None:
        client = Mock()
        listing_error = TwitchAPIError("helix /streams failed")
        client.fetch_english_streams.side_effect = [
            [make_stream("one", 70_000)], [], listing_error, [], [], listing_error, [],
        ]
        client.fetch_live_streams_by_user_ids.side_effect = [
            {}, TwitchAPIError("lookup failed"), {}, {},
        ]
        monitor = TwitchStreamMonitor(client=client)
        cycles = [monitor.poll_once() for _ in range(7)]
        ended = [s for cycle in cycles for s in cycle.ended_streams]
        self.assertEqual([c.ended_streams != () for c in cycles],
                         [False, False, False, False, False, False, True])
        self.assertEqual((ended[0].peak_viewers, ended[0].clip_budget), (70_000, 15))

    def test_peak_budget_reaches_the_vod_acquisition(self) -> None:
        import tempfile
        from pathlib import Path
        from twitch_auto_clipper.twitch_api import TwitchVOD
        from twitch_auto_clipper.vod_acquisition import TwitchVODAcquisitionManager

        live_low = {"broadcaster-one": make_stream("one", 1_000)}
        monitor, cycles = self._peak_scenario(
            listing=[[make_stream("one", 70_000)], [], [], [], []],
            lookups=[live_low, {}, {}, {}],
        )
        api = Mock()
        api.find_vod_for_stream.return_value = TwitchVOD("vod-1", "one", "broadcaster-one", "t")
        with tempfile.TemporaryDirectory() as directory:
            manager = TwitchVODAcquisitionManager(
                monitor=monitor, api_client=api, input_dir=Path(directory) / "in",
                state_path=Path(directory) / "state.json",
                downloader=Mock(return_value=Path(directory) / "in" / "vod-1.mp4"),
            )
            results = manager.process_cycle(cycles[-1])
        self.assertEqual([(r.status, r.clip_budget) for r in results], [("downloaded", 15)])

    def test_console_output_is_concise(self) -> None:
        from twitch_auto_clipper.twitch_monitor import format_monitoring_cycle

        client = Mock()
        listed = [make_stream("big", 60_000), make_stream("mid", 12_000)] + [
            make_stream(f"small{i}", 10) for i in range(2_000)
        ]
        client.fetch_english_streams.side_effect = [listed, [
            make_stream("big", 49_000), make_stream("mid", 12_500)
        ] + listed[2:], listed]
        monitor = TwitchStreamMonitor(client=client)
        first = format_monitoring_cycle(monitor.poll_once())
        second = format_monitoring_cycle(monitor.poll_once())

        self.assertEqual(first[0].split(":")[0], "Cycle Twitch ")
        self.assertIn("2002 streams anglais parcourus, 2 avec budget > 0", first[0])
        self.assertEqual(first[1], "Budgets : 15 clips x1, 5 clips x1")
        self.assertEqual(len(first), 4)  # summary + budgets + 2 eligible new streams
        self.assertFalse(any("small" in line for line in first + second))
        # Only the budget-changing viewer update is shown (60k -> 49k: 15 -> 10 clips).
        self.assertEqual([line for line in second if line.startswith("Viewers")], [
            "Viewers modifies : Broadcaster big (@login-big) - 60000 -> 49000 - budget : 10 clips"
        ])
        verbose = format_monitoring_cycle(monitor.poll_once(), verbose=True)
        self.assertEqual(sum(line.startswith("  suivi") for line in verbose), 2)

    def test_disappearance_is_confirmed_after_consecutive_successful_polls(self) -> None:
        one = [make_stream("one", 5_000)]
        self.assertEqual(
            self._ended_per_poll([one, [], [], [], []]),
            [[], [], [], ["one"], []],
        )

    def test_temporary_disappearance_does_not_end_the_stream(self) -> None:
        one = [make_stream("one", 5_000)]
        self.assertEqual(
            self._ended_per_poll([one, [], [], one, [], [], one]),
            [[], [], [], [], [], [], []],
        )

    def test_api_errors_between_polls_do_not_count_as_disappearances(self) -> None:
        one = [make_stream("one", 5_000)]
        error = TwitchAPIError("temporary network failure")
        self.assertEqual(
            self._ended_per_poll([one, [], error, error, [], error, []]),
            [[], [], [], [], [], [], ["one"]],
        )

    def test_single_confirmation_keeps_the_immediate_behaviour(self) -> None:
        one = [make_stream("one", 5_000)]
        self.assertEqual(self._ended_per_poll([one, [], []], confirmations=1), [[], ["one"], []])

    def test_reappearing_stream_is_not_rediscovered(self) -> None:
        client = Mock()
        one = [make_stream("one", 5_000)]
        client.fetch_english_streams.side_effect = [one, [], one]
        monitor = TwitchStreamMonitor(client=client)
        monitor.poll_once()
        monitor.poll_once()
        self.assertEqual(monitor.poll_once().newly_discovered, ())

    def test_run_uses_configured_interval_and_keeps_going_after_api_error(self) -> None:
        class StopAfterTwoWaits:
            def __init__(self) -> None:
                self.waits = []

            def is_set(self) -> bool:
                return False

            def wait(self, interval: float) -> bool:
                self.waits.append(interval)
                return len(self.waits) == 2

        client = Mock()
        client.fetch_english_streams.side_effect = [
            TwitchAPIError("temporary network failure"),
            [make_stream("one", 5_000)],
        ]
        stop_event = StopAfterTwoWaits()
        cycles = []
        monitor = TwitchStreamMonitor(client=client, polling_interval_seconds=12.5)

        monitor.run(cycles.append, stop_event)

        self.assertEqual([cycle.error is not None for cycle in cycles], [True, False])
        self.assertEqual(stop_event.waits, [12.5, 12.5])
        self.assertEqual(client.fetch_english_streams.call_count, 2)

    def test_run_stops_after_max_cycles_without_waiting_after_the_last(self) -> None:
        from threading import Event

        client = Mock()
        client.fetch_english_streams.return_value = [make_stream("one", 5_000)]
        stop_event = Mock(wraps=Event())
        cycles = []
        monitor = TwitchStreamMonitor(client=client, polling_interval_seconds=0.01)

        monitor.run(cycles.append, stop_event, max_cycles=3)

        self.assertEqual(len(cycles), 3)
        self.assertEqual(stop_event.wait.call_count, 2)

    def test_polling_interval_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            TwitchStreamMonitor(polling_interval_seconds=0)


if __name__ == "__main__":
    unittest.main()