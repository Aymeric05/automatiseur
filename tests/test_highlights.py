from pathlib import Path
import json
import tempfile
import unittest

from twitch_auto_clipper.highlights import (
    HighlightAnalysisError,
    analyze_transcription,
    split_sentences,
    load_transcription,
    save_highlights,
)


class HighlightTests(unittest.TestCase):
    def test_analyze_transcription_scores_reactions_and_punctuation(self) -> None:
        segments = [
            {"start": 10, "end": 15, "text": "Oh my god!!! What happened?"},
            {"start": 20, "end": 24, "text": "Une phrase ordinaire."},
        ]

        candidates = analyze_transcription(segments)

        # The ordinary sentence no longer earns a candidate just for its length.
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["start"], 10.0)
        self.assertGreater(candidates[0]["score"], 3.0)

    def test_analyze_transcription_scores_repeated_words(self) -> None:
        candidates = analyze_transcription(
            [{"start": 0, "end": 4, "text": "Non non non, c'est incroyable!"}]
        )

        self.assertEqual(len(candidates), 1)
        self.assertGreaterEqual(candidates[0]["score"], 3.0)

    def test_analyze_transcription_can_limit_candidates(self) -> None:
        segments = [
            {"start": 0, "end": 4, "text": "Wow!"},
            {"start": 10, "end": 14, "text": "No way!"},
        ]

        candidates = analyze_transcription(segments, max_candidates=1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["start"], 10.0)

    def test_transcription_json_can_be_loaded_and_saved(self) -> None:
        segments = [{"start": 1, "end": 2, "text": "Wow!", "words": []}]
        candidates = analyze_transcription(segments)

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "transcript.json"
            output_path = Path(temporary_directory) / "highlights.json"
            input_path.write_text(json.dumps(segments), encoding="utf-8")

            self.assertEqual(load_transcription(input_path), segments)
            save_highlights(candidates, output_path)
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(saved, candidates)

    def test_load_transcription_rejects_non_list_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "invalid.json"
            input_path.write_text("{}", encoding="utf-8")

            with self.assertRaises(HighlightAnalysisError):
                load_transcription(input_path)

    def test_segments_cut_mid_sentence_are_merged_into_one_sentence(self) -> None:
        sentences = split_sentences([
            {"start": 0.0, "end": 3.0, "text": "I think it's fine to question a character's"},
            {"start": 3.4, "end": 5.0, "text": "like where her head's at."},
            {"start": 5.2, "end": 6.0, "text": "Next one."},
            {"start": 9.0, "end": 10.0, "text": "after a long pause"},
        ])
        self.assertEqual([(s["start"], s["end"]) for s in sentences], [(0.0, 5.0), (5.2, 6.0), (9.0, 10.0)])
        self.assertEqual(sentences[0]["text"], "I think it's fine to question a character's like where her head's at.")

    def test_candidate_starts_at_the_sentence_start_not_mid_sentence(self) -> None:
        segments = [
            {"start": 0.0, "end": 4.0, "text": "What if because what she's doing to him is"},
            {"start": 4.2, "end": 7.0, "text": "exactly what she did before? No way!"},
            {"start": 7.3, "end": 12.0, "text": "That would be a disaster."},
        ]
        candidate = analyze_transcription(segments)[0]
        self.assertEqual(candidate["start"], 0.0)  # not 4.2, where the reaction is
        self.assertEqual(candidate["end"], 12.0)
        self.assertEqual((candidate["highlight_start"], candidate["highlight_end"]), (0.0, 7.0))

    def test_candidate_grows_to_minimum_length_without_passing_the_vod_end(self) -> None:
        segments = [
            {"start": 100.0, "end": 102.0, "text": "Oh my god!"},
            {"start": 102.3, "end": 104.0, "text": "Did you see that?"},
            {"start": 104.2, "end": 106.0, "text": "That was the end."},
        ]
        candidate = analyze_transcription(segments)[0]
        self.assertEqual((candidate["start"], candidate["end"]), (100.0, 106.0))  # last sentence

    def test_overlapping_candidates_keep_only_the_best(self) -> None:
        segments = [
            {"start": 0.0, "end": 3.0, "text": "No way!"},
            {"start": 3.2, "end": 6.0, "text": "Oh my god, what just happened?"},
            {"start": 6.2, "end": 14.0, "text": "He really did it."},
            {"start": 60.0, "end": 63.0, "text": "Let's go!"},
        ]
        candidates = analyze_transcription(segments)
        self.assertEqual(len(candidates), 2)
        for i, a in enumerate(candidates):
            for b in candidates[i + 1:]:
                overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
                shorter = min(a["end"] - a["start"], b["end"] - b["start"])
                self.assertLessEqual(max(0.0, overlap) / shorter, 0.25)

    def test_moments_without_keywords_are_detected(self) -> None:
        calm = [{"start": i * 4.0, "end": i * 4.0 + 3.0, "text": "We walk to the next town now."}
                for i in range(10)]
        fast = {"start": 40.0, "end": 42.0,
                "text": "He took the car and the money and the dog and left us all"}
        exchange = [{"start": 60.0, "end": 62.0, "text": "Wait, who called you"},
                    {"start": 62.0, "end": 62.5, "text": "then?"},
                    {"start": 62.8, "end": 66.0, "text": "My ex, obviously."}]
        candidates = analyze_transcription(calm + [fast] + exchange)
        starts = {c["start"] for c in candidates}
        self.assertIn(40.0, {c["highlight_start"] for c in candidates})  # fast speech
        self.assertIn(60.0, starts)  # question answered in the window
        self.assertFalse(any(c["highlight_start"] < 40 for c in candidates))  # calm talk ignored

    def test_filler_repetition_is_not_rewarded(self) -> None:
        self.assertEqual(
            analyze_transcription([{"start": 0, "end": 5, "text": "I think it's I think it's fine."}]),
            [],
        )


class ExpandMomentTests(unittest.TestCase):
    def test_lead_in_goes_back_to_where_the_excitement_starts(self) -> None:
        from twitch_auto_clipper.highlights import expand_moment

        # Real Jynxzi moment: quiet fight, then death and screams 10 s before the first words.
        levels = [-33, -31, -36, -41, -38, -35, -33, -38, -35, -28, -26, -26, -28, -22, -24, -21, -24, -21, -25, -28]
        start, end = expand_moment(100.0, 112.9, [], levels)
        self.assertEqual(start, 85.0)  # 11 s of excitement + 4 s of set-up, capped at 15 s
        self.assertEqual(end, 112.9)  # 27.9 s: already above the minimum

    def test_without_a_trigger_a_short_set_up_and_the_full_reaction(self) -> None:
        from twitch_auto_clipper.highlights import expand_moment

        sentences = [
            {"start": 100.0, "end": 104.0, "text": "No way!"},
            {"start": 105.0, "end": 109.0, "text": "He did that?"},
            {"start": 110.5, "end": 114.0, "text": "Unbelievable."},
            {"start": 125.0, "end": 128.0, "text": "Anyway, back to the game."},
        ]
        start, end = expand_moment(100.0, 104.0, sentences, [-40.0] * 20)  # flat: no trigger
        self.assertEqual(start, 97.0)  # default 3 s set-up
        self.assertEqual(end, 115.0)  # the reaction goes on, then padded to the 18 s minimum

    def test_never_longer_than_the_maximum(self) -> None:
        from twitch_auto_clipper.highlights import MAX_SHORT_SECONDS, expand_moment

        sentences = [{"start": 100.0 + 5 * i, "end": 104.0 + 5 * i, "text": "Talking."} for i in range(20)]
        start, end = expand_moment(100.0, 104.0, sentences, [-40.0] * 20)
        self.assertLessEqual(end - start, MAX_SHORT_SECONDS)


class AudioLevelsTests(unittest.TestCase):
    def test_ffmpeg_levels_are_parsed_and_silence_is_floored(self) -> None:
        from twitch_auto_clipper.video import parse_audio_levels

        output = "lavfi.astats.Overall.RMS_level=-23.5\nlavfi.astats.Overall.RMS_level=-inf\n"
        self.assertEqual(parse_audio_levels(output), [-23.5, -90.0])


if __name__ == "__main__":
    unittest.main()
