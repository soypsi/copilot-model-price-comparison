import unittest

from scripts.update_models import build_columns, change_summary


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


class BuildColumnsTests(unittest.TestCase):
    def test_release_status_is_never_a_column(self):
        rows = [{"Provider": "Anthropic", "Model": "Claude Fable 5", "Release status": "GA", "Novel": "x"}]
        self.assertNotIn("Release status", build_columns(rows))


if __name__ == "__main__":
    unittest.main()
