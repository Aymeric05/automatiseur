from pathlib import Path
import json
import tempfile
import unittest

from twitch_auto_clipper.chat_activity import (
    add_chat_messages,
    add_chat_activity,
    count_messages_in_window,
    load_chat_messages,
)


class ChatActivityTests(unittest.TestCase):
    def test_load_chat_messages_extracts_timestamps(self) -> None:
        chat = {
            "comments": [
                {"content_offset_seconds": 10, "message": {"body": "wow"}},
                {"content_offset_seconds": 45, "message": {"body": "lol"}},
            ]
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "chat.json"
            path.write_text(json.dumps(chat), encoding="utf-8")
            messages = load_chat_messages(path)

        self.assertEqual([message["timestamp"] for message in messages], [10.0, 45.0])

    def test_count_messages_in_window_is_explainable(self) -> None:
        messages = [{"timestamp": 10}, {"timestamp": 20}, {"timestamp": 70}]

        self.assertEqual(count_messages_in_window(messages, 20, 15), 2)

    def test_add_chat_activity_keeps_candidates_and_adds_count(self) -> None:
        candidates = [{"start": 20.0, "end": 25.0, "score": 2.0}]
        messages = [{"timestamp": 10}, {"timestamp": 35}, {"timestamp": 100}]

        enriched = add_chat_activity(candidates, messages, 15)

        self.assertEqual(enriched[0]["start"], 20.0)
        self.assertEqual(enriched[0]["chat_messages"], 2)

    def test_add_chat_messages_attaches_timestamped_message_content(self) -> None:
        candidates = [{"start": 20.0, "end": 25.0, "score": 2.0}]
        messages = [
            {"timestamp": 18, "message": {"body": "wow"}},
            {"timestamp": 40, "message": {"body": "outside"}},
        ]

        enriched = add_chat_messages(candidates, messages, 5)

        self.assertEqual(enriched[0]["chat_messages"], 1)
        self.assertEqual(
            enriched[0]["chat_message_details"],
            [{"timestamp": 18.0, "text": "wow"}],
        )


if __name__ == "__main__":
    unittest.main()
