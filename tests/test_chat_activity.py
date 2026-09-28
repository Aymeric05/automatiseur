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



def _comment(offset, body, author="u1", emotes=()):
    """Real TwitchDownloaderCLI comment shape."""
    fragments = [{"text": body, "emoticon": None}] + [
        {"text": e, "emoticon": {"emoticon_id": "1"}} for e in emotes
    ]
    return {"content_offset_seconds": offset, "commenter": {"_id": author, "name": author},
            "message": {"body": " ".join([body, *emotes]).strip(), "fragments": fragments}}


class ChatSignalTests(unittest.TestCase):
    def _messages(self, comments):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.json"
            path.write_text(json.dumps({"comments": comments}), encoding="utf-8")
            return load_chat_messages(path)

    def test_real_comment_text_is_read_from_the_nested_message(self) -> None:
        from twitch_auto_clipper.chat_activity import _message_text

        [message] = self._messages([_comment(3, "what a play")])
        self.assertEqual(_message_text(message), "what a play")

    def test_normalized_timestamps_file_can_be_loaded_again(self) -> None:
        messages = self._messages([_comment(3, "what a play")])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timestamps.json"
            path.write_text(json.dumps(messages), encoding="utf-8")
            reloaded = load_chat_messages(path)
        self.assertEqual([m["timestamp"] for m in reloaded], [3.0])

    def test_signal_uses_lag_local_baseline_authors_laughs_and_reactions(self) -> None:
        from twitch_auto_clipper.chat_activity import chat_signal

        background = [_comment(t, "chatting", f"bg{t}") for t in range(0, 600, 10)]  # 0.1 msg/s
        burst = [
            _comment(401, "too early", "z"),  # before the lagged window (402-411)
            _comment(403, "LMAO", "a"), _comment(404, "om", "b"), _comment(404, "om", "c"),
            _comment(405, "", "d", emotes=("raeKek",)), _comment(406, "o", "a"),
            _comment(407, "that was wild", "e"),
            _comment(407, "", "f", emotes=("raeBum", "raeBum")),  # emote spam
            _comment(408, "x subscribed at Tier 1. They've subscribed for 3 months!", "g"),
        ]
        signal = chat_signal(self._messages(background + burst), 400, 403)
        self.assertEqual(signal["messages"], 7)  # 6 burst + background at 410
        self.assertEqual(signal["distinct_authors"], 6)
        self.assertEqual(signal["laugh_ratio"], round(2 / 7, 2))  # LMAO + raeKek emote
        self.assertEqual(signal["short_reaction_ratio"], round(1 / 7, 2))  # "o"; "om" is not generic
        self.assertEqual(signal["top_reactions"], [["om", 2]])
        self.assertEqual(signal["sample_messages"], ["that was wild"])
        self.assertGreater(signal["activity_ratio"], 5)  # vs ~0.1 msg/s around
        self.assertTrue(signal["reliable"])

    def test_greetings_notices_and_emote_spam_are_excluded(self) -> None:
        from twitch_auto_clipper.chat_activity import chat_signal

        noise = [_comment(12, "hiii", "a"), _comment(13, "hello", "b"),
                 _comment(13, "", "c", emotes=("raeHi",)),
                 _comment(14, "", "d", emotes=("chatterboxWaving",)),
                 _comment(14, "hi rae", "h"), _comment(14, "hiii rae and chat", "i"),
                 _comment(15, "hihi", "j"), _comment(15, "Good morning everyone", "k"),
                 _comment(15, "bob watched 12 consecutive streams and sparked a watch streak!", "l"),
                 _comment(15, "", "m", emotes=("raeWiggle",))]
        kept = [_comment(14, "o", "e"), _comment(15, "hey that was actually insane", "n")]
        signal = chat_signal(self._messages(noise + kept), 5, 10)
        self.assertEqual((signal["messages"], signal["distinct_authors"]), (2, 2))

    def test_local_baseline_is_cut_at_the_vod_bounds(self) -> None:
        from twitch_auto_clipper.chat_activity import add_chat_signals

        steady = self._messages([_comment(t, "chatting", f"u{t}") for t in range(0, 300)])  # 1 msg/s
        first, last = add_chat_signals([{"start": 0, "end": 5}, {"start": 290, "end": 295}], steady)
        for candidate in (first, last):
            self.assertAlmostEqual(candidate["chat_signal"]["activity_ratio"], 1.0, delta=0.2)
        self.assertFalse(first["chat_signal"]["reliable"])  # stream start

    def test_silent_surroundings_give_no_ratio(self) -> None:
        from twitch_auto_clipper.chat_activity import chat_signal

        signal = chat_signal(self._messages([_comment(407, "o")]), 400, 405)
        self.assertIsNone(signal["activity_ratio"])
        self.assertFalse(signal["reliable"])
        self.assertEqual(chat_signal([], 0, 5)["messages"], 0)


if __name__ == "__main__":
    unittest.main()
