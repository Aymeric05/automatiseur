"""Tests for Short titles and descriptions built from the real transcript."""

import unittest

from twitch_auto_clipper.shorts_metadata import (
    ShortMetadataError,
    build_short_metadata,
    clip_transcript_text,
)

SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "warming up the stream"},
    {
        "start": 10.0, "end": 14.0, "text": "no way he hit that shot",
        "words": [
            {"start": 10.0, "end": 10.4, "word": "no"},
            {"start": 10.4, "end": 10.8, "word": "way"},
            {"start": 11.0, "end": 11.3, "word": "he"},
            {"start": 11.3, "end": 11.6, "word": "hit"},
            {"start": 11.6, "end": 12.0, "word": "that"},
            {"start": 12.0, "end": 12.5, "word": "shot"},
        ],
    },
    {"start": 15.0, "end": 18.0, "text": "chat <clip> it"},
]


class ShortsMetadataTests(unittest.TestCase):
    def test_title_quotes_the_highlighted_moment(self):
        metadata = build_short_metadata(
            broadcaster_name="Streamer", broadcaster_login="streamer", vod_id="123",
            segments=SEGMENTS, clip_start=5.0, clip_end=19.0,
            candidate_start=10.0, candidate_end=14.0,
        )
        self.assertEqual(metadata.title, "Streamer: “no way he hit that shot”")
        self.assertIn("https://www.twitch.tv/streamer", metadata.description)
        self.assertIn("https://www.twitch.tv/videos/123", metadata.description)
        self.assertIn("no way he hit that shot", metadata.description)

    def test_bare_reaction_title_quotes_the_most_substantial_sentence(self):
        segments = [
            {"start": 0, "end": 2, "text": "Oh my god."},
            {"start": 2, "end": 8, "text": "She just stole the whole bank truck alone."},
            {"start": 8, "end": 9, "text": "Wow."},
        ]
        metadata = build_short_metadata(
            broadcaster_name="Streamer", broadcaster_login="s", vod_id="1", segments=segments,
            clip_start=0, clip_end=9, candidate_start=0, candidate_end=2,
        )
        self.assertEqual(metadata.title, "Streamer: “She just stole the whole bank truck alone.”")

    def test_whisper_word_tokens_are_joined_without_extra_spaces(self):
        segments = [{"start": 0, "end": 3, "text": "and cost $7,000.", "words": [
            {"start": 0.0, "end": 0.5, "word": " and"},
            {"start": 0.5, "end": 1.0, "word": " cost"},
            {"start": 1.0, "end": 1.8, "word": " $7"},
            {"start": 1.8, "end": 2.5, "word": ",000."},
        ]}]
        self.assertEqual(clip_transcript_text(segments, 0, 3), "and cost $7,000.")

    def test_only_words_inside_the_clip_are_used(self):
        self.assertEqual(clip_transcript_text(SEGMENTS, 10.5, 12.5), "way he hit that shot")

    def test_sentence_tail_caught_by_the_margin_is_skipped(self):
        # 3.5-19 overlaps only the last 1.5 s of the 5 s opening segment.
        self.assertEqual(
            clip_transcript_text(SEGMENTS, 3.5, 19.0),
            "no way he hit that shot chat <clip> it".replace("<", "").replace(">", ""),
        )

    def test_forbidden_characters_are_removed(self):
        metadata = build_short_metadata(
            broadcaster_name="Streamer", broadcaster_login="streamer", vod_id="123",
            segments=SEGMENTS, clip_start=15.0, clip_end=18.0,
        )
        self.assertNotIn("<", metadata.title + metadata.description)
        self.assertNotIn(">", metadata.title + metadata.description)

    def test_long_quotes_fit_youtube_title_limit(self):
        segments = [{"start": 0, "end": 10, "text": " ".join(["incredible"] * 60)}]
        metadata = build_short_metadata(
            broadcaster_name="S" * 60, broadcaster_login="s", vod_id="1",
            segments=segments, clip_start=0, clip_end=10,
        )
        self.assertLessEqual(len(metadata.title), 100)

    def test_no_transcript_text_raises_instead_of_inventing(self):
        with self.assertRaises(ShortMetadataError):
            build_short_metadata(
                broadcaster_name="Streamer", broadcaster_login="streamer", vod_id="1",
                segments=SEGMENTS, clip_start=100, clip_end=110,
            )


if __name__ == "__main__":
    unittest.main()
