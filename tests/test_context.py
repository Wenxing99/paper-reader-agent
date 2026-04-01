from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
if REPO_ROOT.name == "tests":
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from paper_reader_agent.config import load_config
from paper_reader_agent.services.bridge import normalize_reasoning_effort
from paper_reader_agent.services.context import pick_relevant_pages
from paper_reader_agent.services.obsidian import slugify


class ContextTests(unittest.TestCase):
    def test_pick_relevant_pages_prefers_matching_terms(self) -> None:
        pages = [
            {"page_number": 1, "text": "Introduction and motivation."},
            {"page_number": 2, "text": "Method details about transformer attention and ablation."},
            {"page_number": 3, "text": "Results and error analysis."},
        ]

        selected = pick_relevant_pages("What does the attention ablation show?", pages, current_page=1, limit=2)
        self.assertEqual([page["page_number"] for page in selected], [2, 1])

    def test_slugify_is_obsidian_friendly(self) -> None:
        self.assertEqual(slugify("A Great Paper: 2026 Edition"), "a-great-paper-2026-edition")

    def test_config_defaults_keep_local_stack(self) -> None:
        config = load_config()
        self.assertEqual(config.port, 8790)
        self.assertTrue(config.bridge_url.endswith("/v1"))

    def test_reasoning_effort_maps_median_to_medium(self) -> None:
        self.assertEqual(normalize_reasoning_effort("median"), "medium")

    def test_reasoning_effort_default_is_empty(self) -> None:
        self.assertEqual(normalize_reasoning_effort("default"), "")


if __name__ == "__main__":
    unittest.main()
