import unittest

from scripts.update_models import build_columns, change_summary, normalize_rows, render_static_page


class ChangeSummaryTests(unittest.TestCase):
    def test_tier_metadata_changes_do_not_report_existing_models_as_added_or_removed(self):
        previous = [
            {
                "Provider": "Anthropic",
                "Model": "Claude Sonnet 5.5",
                "Tier": "",
                "Threshold (input tokens)": "",
                "Total price": "$14.7",
                "Cached input": "$0.20",
            }
        ]
        current = [
            {
                "Provider": "Anthropic",
                "Model": "Claude Sonnet 5.5",
                "Tier": "Default",
                "Threshold (input tokens)": "Not applicable",
                "Total price": "$14.6",
                "Cached input": "$0.10",
            },
            {
                "Provider": "Anthropic",
                "Model": "Claude Haiku 5.5",
                "Tier": "Default",
                "Threshold (input tokens)": "≤ 100K",
                "Total price": "$0.735",
                "Cached input": "$0.01",
            },
            {
                "Provider": "Anthropic",
                "Model": "Claude Haiku 5.5",
                "Tier": "Long context",
                "Threshold (input tokens)": "> 100K",
                "Total price": "$3.675",
                "Cached input": "$0.05",
            },
        ]

        self.assertEqual(
            change_summary(previous, current),
            [
                "New models: Claude Haiku 5.5",
                "Price changes: Claude Sonnet 5.5 (Default): $14.7 → $14.6",
            ],
        )


class ParsePriceTests(unittest.TestCase):
    def test_unparseable_price_names_the_offending_cell(self):
        rows = [{"Provider": "OpenAI", "Model": "GPT-5", "Tier": "Default", "Input": "1.25", "Output": "free"}]
        with self.assertRaises(ValueError) as failure:
            normalize_rows(rows, ["Provider", "Model", "Tier", "Input", "Output"], [], {})
        message = str(failure.exception)
        self.assertIn("'free'", message)
        self.assertIn("OpenAI GPT-5 Output", message)


class BuildColumnsTests(unittest.TestCase):
    def test_release_status_is_never_a_column(self):
        rows = [{"Provider": "Anthropic", "Model": "Claude Fable 5", "Release status": "GA", "Novel": "x"}]
        self.assertNotIn("Release status", build_columns(rows))


class StaticPageTests(unittest.TestCase):
    def test_static_page_renders_escaped_table_and_changelog(self):
        template = "".join(
            f"<!-- STATIC:{name}:START --><!-- STATIC:{name}:END -->"
            for name in ("ROW_COUNT", "SOURCE", "UPDATED", "TABLE", "CHANGELOG")
        )
        payload = {
            "updated_at": "2026-10-29T06:38:17Z",
            "source_url": "https://example.test/pricing?a=1&b=2",
            "leaderboard_url": "https://example.test/leaderboard",
            "columns": [
                "Model",
                "Threshold (input tokens)",
                "Cached input",
                "Cache write",
                "Total price",
                "Coding rank",
            ],
            "rows": [{
                "Model": "<Model>",
                "Threshold (input tokens)": "Not applicable",
                "Cached input": "$0.5",
                "Cache write": "$1",
                "Total price": "$2",
                "Coding rank": "7",
                "_category_scores": {
                    "coding": 71.36,
                    "agentic": 75.25,
                    "reasoning": 84.3,
                    "multimodalGrounded": 91,
                    "multilingual": None,
                },
            }, {
                "Model": "Other",
                "Threshold (input tokens)": "100K",
                "Cached input": "",
                "Cache write": "",
                "Total price": "$3",
                "Coding rank": "8",
                "_category_scores": {
                    "coding": 70,
                    "agentic": None,
                    "reasoning": 80,
                    "multimodalGrounded": 88,
                    "multilingual": None,
                },
            }, {
                "Model": "Lower score",
                "Threshold (input tokens)": "",
                "Cached input": "",
                "Cache write": "",
                "Total price": "$4",
                "Coding rank": "9",
                "_category_scores": {
                    "coding": 69,
                    "agentic": 55,
                    "reasoning": 81,
                    "multimodalGrounded": 75,
                    "multilingual": None,
                },
            }],
            "changelog": [
                {"updated_at": "2026-10-20", "changes": ["Older update"]},
                {"updated_at": "2026-10-29", "changes": ["Latest update"]},
            ],
        }

        page = render_static_page(template, payload)

        self.assertIn("&lt;Model&gt;", page)
        self.assertNotIn("<Model>", page)
        self.assertIn("$0.5 / $1", page)
        self.assertIn('data-column="Threshold (input tokens)" class="numeric-column">Context</th>', page)
        self.assertIn('data-column="Coding rank" class="numeric-column">Coding</th>', page)
        self.assertIn('data-column="Score: multimodalGrounded">Multimodal</th>', page)
        self.assertIn('data-column="Score: agentic"', page)
        self.assertIn(">75</td>", page)
        self.assertNotIn(">75.25</td>", page)
        self.assertIn('--score-hue:120deg', page)
        self.assertIn('--score-hue:0deg', page)
        self.assertIn('data-column="Coding rank" class="numeric-column score-heat-cell" style="--score-hue:120deg">7</td>', page)
        self.assertIn(">84</td>", page)
        self.assertIn('<td data-column="Score: agentic" class="numeric-column category-score-column"></td>', page)
        self.assertNotIn('data-column="Score: multilingual"', page)
        self.assertNotIn(">n/a</td>", page)
        self.assertIn("<strong>2026-10-29</strong>: Latest update", page)
        self.assertIn('<details class="changelog-older">', page)
        self.assertIn("a=1&amp;b=2", page)
        self.assertIn("<!-- STATIC:TABLE:START -->", page)
        self.assertNotIn("Loading…", page)


if __name__ == "__main__":
    unittest.main()
