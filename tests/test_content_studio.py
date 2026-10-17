import os
import unittest
from unittest.mock import Mock, patch

from backend.ai_generation import (
    WRITER_PROFILE,
    InvalidGenerationRequest,
    build_pack_prompt,
    validate_angles_payload,
    validate_pack_payload,
    validate_requested_model,
)
from backend.model_catalog import ModelCatalog


def valid_pack():
    return {
        "instagram": {
            "caption": " ".join(["thoughtful"] * 120),
            "hashtags": ["#software", "#learning", "#ai"],
            "carousel": [{"slide": i, "heading": f"Slide {i}", "body": "Grounded idea"} for i in range(1, 7)],
            "visual_direction": "Simple annotated notebook frames.",
            "alt_text": "Six slides explaining a software learning idea.",
        },
        "x": {"single": "A grounded thought.", "thread": [f"Part {i}" for i in range(1, 6)]},
        "threads": "A grounded thought worth discussing.",
    }


class GenerationValidationTests(unittest.TestCase):
    def test_requires_exactly_three_complete_angles(self):
        angles = [{"id": str(i), "title": "Title", "hook": "Hook", "lens": "Lens", "grounding": "Source idea"} for i in range(3)]
        validate_angles_payload({"angles": angles})
        with self.assertRaises(ValueError):
            validate_angles_payload({"angles": angles[:2]})

    def test_enforces_platform_limits(self):
        pack = valid_pack()
        validate_pack_payload(pack)
        pack["x"]["single"] = "x" * 281
        with self.assertRaisesRegex(ValueError, "280"):
            validate_pack_payload(pack)

    def test_rejects_models_outside_live_allowlist(self):
        with self.assertRaises(InvalidGenerationRequest):
            validate_requested_model("unknown/model", {"known/model"})


class VoicePromptTests(unittest.TestCase):
    angle = {"id": "1", "title": "T", "hook": "H", "lens": "L", "grounding": "G"}

    def test_includes_interview_answers_and_published_posts(self):
        profile = {
            "interview": [
                {"question": "What are you building?", "answer": "a podcast app that keeps crashing lol"},
                {"question": "Unanswered?", "answer": "  "},
            ],
            "examples": ["my first real post"],
            "avoid_phrases": ["synergy"],
        }
        prompt = build_pack_prompt("TRANSCRIPT", "", {}, profile, "curious", self.angle)
        self.assertIn("a podcast app that keeps crashing lol", prompt)
        self.assertNotIn("Unanswered?", prompt)
        self.assertIn("<post>my first real post</post>", prompt)
        self.assertIn("synergy", prompt)
        self.assertIn("game-changer", prompt)

    def test_falls_back_to_default_bio_and_puts_instructions_after_transcript(self):
        prompt = build_pack_prompt("TRANSCRIPT", "", {}, {}, "curious", self.angle)
        self.assertIn(WRITER_PROFILE, prompt)
        self.assertLess(prompt.index("TRANSCRIPT"), prompt.index("Task:"))


class ModelCatalogTests(unittest.TestCase):
    @patch("backend.model_catalog.requests.get")
    def test_gates_catalog_by_schema_support_and_price(self, get: Mock):
        response = Mock()
        response.json.return_value = {"data": [
            {"id": "cheap/model", "name": "Cheap", "supported_parameters": ["response_format"], "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
            {"id": "expensive/model", "name": "Expensive", "supported_parameters": ["response_format"], "pricing": {"prompt": "0.000003", "completion": "0.000009"}},
        ]}
        response.raise_for_status.return_value = None
        get.return_value = response
        with patch.dict(os.environ, {"CONTENT_MODEL_IDS": "cheap/model,expensive/model", "CONTENT_DEFAULT_MODEL": "cheap/model"}, clear=False):
            result = ModelCatalog().get_models()
        self.assertTrue(result["models"][0]["enabled"])
        self.assertFalse(result["models"][1]["enabled"])

    @patch("backend.model_catalog.requests.get")
    def test_safe_fallback_enables_only_default(self, get: Mock):
        import requests
        get.side_effect = requests.RequestException("offline")
        with patch.dict(os.environ, {"CONTENT_MODEL_IDS": "default/model,other/model", "CONTENT_DEFAULT_MODEL": "default/model"}, clear=False):
            result = ModelCatalog().get_models()
        self.assertEqual([item["enabled"] for item in result["models"]], [True, False])


if __name__ == "__main__":
    unittest.main()
