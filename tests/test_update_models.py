import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import update_models
from scripts.update_models import (
    build_columns,
    change_summary,
    leaderboard_models,
    match_leaderboard_model,
    merge_price_columns,
    normalize_rows,
    parse_tables,
    rank_number,
    render_static_page,
    require_ranked_rows,
)


def matched_model(model: str, leaderboard: list[dict]) -> str | None:
    match = match_leaderboard_model(model, leaderboard)
    return match["model"] if match else None


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


class MergePriceColumnsTests(unittest.TestCase):
    def test_merged_price_adds_to_the_existing_target_column(self):
        row = {
            "Provider": "OpenAI",
            "Model": "GPT-5",
            "Text input": "$2.00",
            "Image input": "$1.00",
            "Input": "$5.00",
        }
        merge_price_columns(row)
        self.assertEqual(row["Input"], "$8")
        self.assertNotIn("Text input", row)

    def test_merged_price_keeps_three_decimals(self):
        row = {"Model": "M", "Image input": "$0.333", "Text input": "$0.111", "Input": "Not applicable"}
        merge_price_columns(row)
        self.assertEqual(row["Input"], "$0.444")


class MatchLeaderboardModelTests(unittest.TestCase):
    def test_parenthetical_qualifier_selects_the_variant_not_the_base(self):
        leaderboard = [
            {"model": "GPT-5 mini", "rank": 3},
            {"model": "GPT-5 mini preview", "rank": 9},
        ]
        self.assertEqual(matched_model("GPT-5 mini (preview)", leaderboard), "GPT-5 mini preview")
        self.assertEqual(matched_model("GPT-5 mini (preview)", list(reversed(leaderboard))), "GPT-5 mini preview")

    def test_base_fallback_still_matches_a_suffixed_model(self):
        self.assertEqual(matched_model("GPT-5 mini high", [{"model": "GPT-5 mini", "rank": 3}]), "GPT-5 mini")

    def test_ambiguous_base_still_matches_nothing(self):
        leaderboard = [
            {"model": "GPT-5 mini", "rank": 3},
            {"model": "GPT-5 mini preview", "rank": 9},
        ]
        self.assertIsNone(matched_model("GPT-5 mini high", leaderboard))


class RankNumberTests(unittest.TestCase):
    def test_non_ascii_digits_do_not_abort_the_update(self):
        self.assertEqual(rank_number("12"), 12)
        self.assertIsNone(rank_number("²"))
        self.assertIsNone(rank_number(""))

    def test_rank_diff_stays_empty_for_unparseable_previous_rank(self):
        rows = [{"Provider": "P", "Model": "M", "Input": "$1"}]
        leaderboard = [{"model": "M", "rank": 5, "categoryScores": {}}]
        previous = {("P", "M", "Default", "Not applicable"): {"Coding rank": "²"}}
        row = normalize_rows(rows, ["Provider", "Model", "Input", "Total price"], leaderboard, previous)[0]
        self.assertEqual(row["_coding_rank_diff"], "")
        self.assertEqual(row["Coding rank"], "5")


class BuildColumnsTests(unittest.TestCase):
    def test_release_status_is_never_a_column(self):
        rows = [{"Provider": "Anthropic", "Model": "Claude Fable 5", "Release status": "GA", "Novel": "x"}]
        self.assertNotIn("Release status", build_columns(rows))


class ParseTablesTests(unittest.TestCase):
    def test_void_tag_inside_sup_does_not_shift_the_row_left(self):
        rendered = (
            "<h2>Anthropic</h2><table>"
            "<tr><th>Model</th><th>Input</th></tr>"
            "<tr><td>Claude Fable 5<sup>note<img src=x></sup></td><td>$10.00</td></tr>"
            "</table>"
        )
        self.assertEqual(
            parse_tables(rendered),
            [{"Provider": "Anthropic", "Model": "Claude Fable 5", "Input": "$10.00"}],
        )


class LeaderboardGuardTests(unittest.TestCase):
    def test_empty_leaderboard_aborts_instead_of_blanking_the_site(self):
        with self.assertRaises(RuntimeError) as failure:
            leaderboard_models({"data": []})
        self.assertIn("leaderboard", str(failure.exception))
        self.assertEqual(leaderboard_models({"models": [{"model": "M", "rank": 1}]}), [{"model": "M", "rank": 1}])

    def test_rows_without_any_rank_aborts(self):
        with self.assertRaises(RuntimeError):
            require_ranked_rows([{"Model": "M", "Coding rank": ""}])
        require_ranked_rows([{"Model": "M", "Coding rank": "7"}])


class WriteOrderTests(unittest.TestCase):
    def test_render_failure_leaves_committed_files_untouched(self):
        rendered = (
            "<h2>Anthropic</h2><table>"
            "<tr><th>Model</th><th>Input</th></tr>"
            "<tr><td>Claude Fable 5</td><td>$10.00</td></tr>"
            "</table>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.html"
            index_path.write_text("<!-- STATIC:ROW_COUNT:START --><!-- STATIC:ROW_COUNT:END -->")
            output_path = root / "data" / "models.json"
            output_path.parent.mkdir()
            output_path.write_text(json.dumps({"rows": [], "changelog": []}))
            before = (index_path.read_text(), output_path.read_text())
            with mock.patch.object(update_models, "fetch_html", return_value=""), \
                    mock.patch.object(update_models, "extract_rendered_page", return_value=rendered), \
                    mock.patch.object(update_models, "fetch_json", return_value={
                        "models": [{"model": "Claude Fable 5", "rank": 3, "categoryScores": {}}]
                    }), \
                    mock.patch.object(update_models, "INDEX_PATH", index_path), \
                    mock.patch.object(update_models, "OUTPUT_PATH", output_path), \
                    mock.patch.object(update_models, "RSS_PATH", root / "feed.xml"):
                with self.assertRaises(RuntimeError):
                    update_models.main()
            self.assertEqual((index_path.read_text(), output_path.read_text()), before)


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
                "Tier",
                "Threshold (input tokens)",
                "Cached input",
                "Cache write",
                "Total price",
                "Coding rank",
            ],
            "rows": [{
                "Model": "<Model>",
                "Tier": "Default",
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
                "Tier": "Long context",
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
        self.assertIn('class="mobile-cache" title="Cached input + cache write">$1.5</td>', page)
        self.assertNotIn('<th aria-label="Select"></th>', page)
        self.assertNotIn('<td></td><td data-column="Model"', page)
        self.assertNotIn('data-column="Tier"', page)
        self.assertIn('data-column="Threshold (input tokens)" class="numeric-column">Context</th>', page)
        self.assertNotIn(">Default</td>", page)
        self.assertNotIn(">Long context</td>", page)
        self.assertIn('data-column="Threshold (input tokens)" class="numeric-column" title="">', page)
        self.assertIn('title="100K">100K</td>', page)
        self.assertIn('<span class="full-label">Cached input</span><span class="short-label">Cache</span>', page)
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
