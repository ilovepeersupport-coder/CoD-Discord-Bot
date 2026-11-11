"""Offline tests for screenshot guards and scoreboard normalization."""
import unittest
from io import BytesIO

from PIL import Image

from extractor import (
    ImageRejected,
    gemini_models,
    is_model_unavailable,
    is_transient_gemini_error,
    normalize_scoreboard,
    prepare_image_bytes,
)


def _png(width, height, color=(20, 20, 20)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


class TestExtractorGuards(unittest.TestCase):
    def test_prepare_image_reencodes_a_normal_screenshot(self):
        prepared = prepare_image_bytes(_png(64, 64))
        with Image.open(BytesIO(prepared)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreaterEqual(image.width, 16)

    def test_prepare_image_rejects_empty_tiny_and_non_images(self):
        with self.assertRaises(ImageRejected):
            prepare_image_bytes(b"")
        with self.assertRaises(ImageRejected):
            prepare_image_bytes(_png(4, 4))
        with self.assertRaises(ImageRejected):
            prepare_image_bytes(b"this is not an image")
        with self.assertRaises(ImageRejected):
            prepare_image_bytes(b"x" * (8 * 1024 * 1024 + 1))

    def test_normalize_caps_players_and_stats(self):
        players = [{"name": f"Player {index}", "kills": index} for index in range(30)]
        players.append({"name": "  `Shotzzy`\n", "kills": "12", "deaths": -3, "damage": "9,999,999", "team": "OpTic"})
        result = normalize_scoreboard({"players": players, "team1_score": "250"}, "gemini")
        self.assertEqual(len(result["players"]), 16)
        self.assertEqual(result["players"][0]["name"], "Player 0")
        self.assertEqual(result["team1_score"], 250)
        capped = normalize_scoreboard({"players": [players[-1]]}, "gemini")
        row = capped["players"][0]
        self.assertEqual(row["name"], "'Shotzzy'")
        self.assertEqual(row["kills"], 12)
        self.assertEqual(row["deaths"], 0)
        self.assertEqual(row["damage"], 1_000_000)

    def test_gemini_errors_are_classified(self):
        self.assertTrue(is_transient_gemini_error(RuntimeError("503 UNAVAILABLE")))
        self.assertFalse(is_transient_gemini_error(RuntimeError("invalid argument")))
        missing = RuntimeError("model not found")
        self.assertTrue(is_model_unavailable(missing))

    def test_default_models_skip_the_deprecated_alias(self):
        models = gemini_models()
        self.assertIn("gemini-3.8-flash", models)
        self.assertNotIn("gemini-3.5-flash", models)


if __name__ == "__main__":
    unittest.main()
