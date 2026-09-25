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

    def test_successful_empty_snapshot_marks_active_stream_ended(self) -> None:
        client = Mock()
        client.fetch_english_streams.side_effect = [
            [make_stream("one", 5_000)],
            [],
            [],
        ]
        monitor = TwitchStreamMonitor(client=client)

        monitor.poll_once()
        ended_cycle = monitor.poll_once()
        next_cycle = monitor.poll_once()

        self.assertEqual([s.stream.stream_id for s in ended_cycle.ended_streams], ["one"])
        self.assertEqual(next_cycle.ended_streams, ())

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

    def test_polling_interval_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            TwitchStreamMonitor(polling_interval_seconds=0)


if __name__ == "__main__":
    unittest.main()