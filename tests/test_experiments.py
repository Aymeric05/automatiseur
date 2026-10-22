import json
from pathlib import Path
import tempfile
import unittest

from twitch_auto_clipper.experiments import for_vod, rules_text, variant


class ExperimentTests(unittest.TestCase):
    def test_half_of_the_vods_get_variant_b_always_the_same_and_only_on_its_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "experiments.json"
            config.write_text(json.dumps({"experiments": [
                {"id": "short_titles", "channel": "irl", "b": {"selection_rules": ["Titles under 35 characters."]}},
                {"id": "no_cold_open", "channel": "irl", "b": {"cold_open": False}},
                {"id": "gaming_only", "channel": "gaming", "b": {"ideal_seconds": [20, 40]}},
            ]}), encoding="utf-8")
            sides = [variant("short_titles", str(vod)) for vod in range(200)]
            self.assertTrue(80 < sides.count("B") < 120)  # about half
            self.assertEqual(variant("short_titles", "42"), variant("short_titles", "42"))
            vod = next(str(v) for v in range(200) if variant("short_titles", str(v)) == "B")
            variants, settings = for_vod(vod, "irl", config)
            self.assertEqual(set(variants), {"short_titles", "no_cold_open"})  # never the gaming test
            self.assertEqual(settings["selection_rules"], ["Titles under 35 characters."])
            self.assertEqual(for_vod("1", "irl", Path(directory) / "missing.json"), ({}, {}))
        self.assertIn("Titles under 35", rules_text(["Titles under 35 characters."]))
        self.assertEqual(rules_text([]), "")


if __name__ == "__main__":
    unittest.main()
