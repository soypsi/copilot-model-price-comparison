#!/usr/bin/env python3
"""Update pricing data and render the static GitHub Pages site."""

from __future__ import annotations

import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
CHANGELOG_LIMIT: Final = 60
FETCH_TIMEOUT_SECONDS: Final = 60
FETCH_RETRIES: Final = 4
RETRY_DELAY_SECONDS: Final = 2.0
SOURCE_URL: Final = "https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing"
LEADERBOARD_URL: Final = "https://benchlm.ai/api/data/leaderboard?category=coding"
OUTPUT_PATH: Final = ROOT / "data/models.json"
RSS_PATH: Final = ROOT / "important-changes.xml"
INDEX_PATH: Final = ROOT / "index.html"
SITE_URL: Final = "https://soypsi.github.io/copilot-model-price-comparison"
SHORT_COLUMN_NAMES: Final = {
    "Total price": "Price",
    "Cached input": "Cache",
    "Cache write": "Write",
}
NEXT_DATA_RE: Final = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
# Source-page columns we deliberately do not render.
DROP_COLUMNS: Final = {"Release status"}
PREFERRED_COLUMNS: Final = [
    "Provider",
    "Model",
    "Category",
    "Tier",
    "Threshold (input tokens)",
    "Input",
    "Cached input",
    "Cache write",
    "Output",
    "Total price",
    "Coding rank",
]
# Multimodal (image) pricing columns folded into the regular price columns by summing.
MERGE_COLUMNS: Final = {
    "Cached image input": "Cached input",
    "Cached text input": "Cached input",
    "Image input": "Input",
    "Text input": "Input",
    "Image output": "Output",
}
PRICE_SOURCE_COLUMNS: Final = ("Input", "Cached input", "Cache write", "Output")
# Void elements have no end tag, so they must not add depth to a skipped region.
VOID_ELEMENTS: Final = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
PRICE_COLUMNS: Final = (*PRICE_SOURCE_COLUMNS, "Total price")
STATIC_NUMERIC_COLUMNS: Final = {*PRICE_COLUMNS, "Coding rank", "Threshold (input tokens)"}


def context_display_value(row: dict[str, Any]) -> str:
    context = str(row.get("Threshold (input tokens)") or "").strip()
    if context.lower() == "not applicable":
        context = ""
    return context


def mobile_cache_price(row: dict[str, Any]) -> str:
    columns = ("Cached input", "Cache write")
    values = [str(row.get(column) or "").strip() for column in columns]
    if not any(value and value.lower() != "not applicable" for value in values):
        return ""
    total = math.fsum(
        parse_price(value, f"mobile cache {column}")
        for column, value in zip(columns, values)
        if value
    )
    return f"${total:.3f}".rstrip("0").rstrip(".")


def render_static_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    has_cache_columns = "Cached input" in columns and "Cache write" in columns
    category_names = list(dict.fromkeys(
        name for row in rows for name, score in row.get("_category_scores", {}).items()
        if name != "coding" and category_score_text(score)
    ))
    category_ranges = {}
    for category in category_names:
        scores = [
            value for row in rows
            if (value := numeric_category_score(row.get("_category_scores", {}).get(category))) is not None
        ]
        if scores:
            category_ranges[category] = min(scores), max(scores)
    coding_ranks = [
        value for row in rows
        if (value := numeric_category_score(row.get("Coding rank"))) is not None
    ]
    coding_rank_range = (min(coding_ranks), max(coding_ranks)) if coding_ranks else None
    display_columns = []
    for column in columns:
        if column == "Tier":
            continue
        display_columns.append(column)
        if column == "Coding rank":
            display_columns.extend(f"Score: {name}" for name in category_names)
        if column == "Cache write" and has_cache_columns:
            display_columns.append("Mobile cache")
    headers = []
    for column in display_columns:
        if column == "Mobile cache":
            headers.append('<th class="mobile-cache" title="Cached input and cache write prices">Cache</th>')
            continue
        if column.startswith("Score: "):
            category = column[7:]
            headers.append(
                f'<th class="numeric-column category-score-column" data-column="{escape(column)}">'
                f'{escape(category_label(category).split()[0])}</th>'
            )
            continue
        name = escape(column)
        if column == "Coding rank":
            label = "Coding"
        elif column == "Threshold (input tokens)":
            label = "Context"
        else:
            short_name = SHORT_COLUMN_NAMES.get(column)
            label = (
                f'<span class="full-label">{name}</span><span class="short-label">{short_name}</span>'
                if short_name
                else name
            )
        numeric = ' class="numeric-column"' if column in STATIC_NUMERIC_COLUMNS else ""
        headers.append(f'<th data-column="{name}"{numeric}>{label}</th>')

    body = []
    for row in rows:
        cells = []
        for column in display_columns:
            if column == "Mobile cache":
                value = escape(mobile_cache_price(row))
                cells.append(f'<td class="mobile-cache" title="Cached input + cache write">{value}</td>')
                continue
            if column.startswith("Score: "):
                category = column[7:]
                score = row.get("_category_scores", {}).get(category)
                heat = category_score_heat_style(score, category_ranges.get(category))
                cells.append(
                    f'<td data-column="{escape(column)}" class="numeric-column category-score-column'
                    f'{" score-heat-cell" if heat else ""}"{heat}>'
                    f'{escape(category_score_text(score))}</td>'
                )
                continue
            if column == "Coding rank":
                rank = str(row.get(column, ""))
                heat = category_score_heat_style(rank, coding_rank_range, reverse=True)
                cells.append(
                    f'<td data-column="{escape(column)}" class="numeric-column'
                    f'{" score-heat-cell" if heat else ""}"{heat}>{escape(rank)}</td>'
                )
                continue
            raw_value = (
                context_display_value(row)
                if column == "Threshold (input tokens)"
                else str(row.get(column, ""))
            )
            value = escape(raw_value)
            numeric = ' class="numeric-column"' if column in STATIC_NUMERIC_COLUMNS else ""
            title = f' title="{escape(raw_value, quote=True)}"' if column == "Threshold (input tokens)" else ""
            cells.append(f'<td data-column="{escape(column)}"{numeric}{title}>{value}</td>')
        body.append(f"<tr>{''.join(cells)}</tr>")

    return (
        '<table id="pricing-table" aria-label="Model pricing table">'
        f"<thead><tr>{''.join(headers)}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def category_label(category: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", category).replace("_", " ").replace("-", " ")
    return " ".join(word.capitalize() for word in words.split())


def category_score_text(score: Any) -> str:
    if score is None or str(score).strip().lower() == "n/a":
        return ""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return str(score)
    if not math.isfinite(value):
        return ""
    return str(math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5))


def numeric_category_score(score: Any) -> float | None:
    if not category_score_text(score):
        return None
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def category_score_heat_style(
    score: Any, score_range: tuple[float, float] | None, reverse: bool = False
) -> str:
    value = numeric_category_score(score)
    if value is None or score_range is None:
        return ""
    minimum, maximum = score_range
    normalized = 0.5 if minimum == maximum else (
        max(minimum, min(maximum, value)) - minimum
    ) / (maximum - minimum)
    if reverse:
        normalized = 1 - normalized
    hue = normalized * 120
    return f' style="--score-hue:{hue:g}deg"'


def render_static_changelog(changelog: list[dict[str, Any]]) -> str:
    if not changelog:
        return ""
    entries = list(reversed(changelog))

    def format_entry(entry: dict[str, Any]) -> str:
        date = escape(str(entry.get("updated_at", ""))[:10])
        changes = " ".join(escape(str(change)) for change in entry.get("changes", []))
        return f"<li><strong>{date}</strong>: {changes}</li>"

    latest = f"<ul>{format_entry(entries[0])}</ul>"
    older_entries = entries[1:]
    older = ""
    if older_entries:
        older = (
            f'<details class="changelog-older"><summary>Older changes ({len(older_entries)})</summary>'
            f"<ul>{''.join(format_entry(entry) for entry in older_entries)}</ul></details>"
        )
    return (
        '<h2 id="changelog-title">Important changes '
        '<a href="important-changes.xml" target="_blank" rel="noopener noreferrer" '
        'aria-label="Subscribe to important changes RSS feed">📡</a></h2>'
        f"{latest}{older}"
    )


def render_static_page(template: str, payload: dict[str, Any]) -> str:
    source_url = escape(str(payload.get("source_url", "")), quote=True)
    leaderboard_url = escape(str(payload.get("leaderboard_url", "")), quote=True)
    updated_at = escape(str(payload.get("updated_at", "")))
    rows = payload.get("rows", [])
    regions = {
        "ROW_COUNT": f"{len(rows)} pricing rows",
        "SOURCE": (
            f'<span class="source-item">Price Source: <a href="{source_url}" target="_blank" rel="noopener noreferrer">Models and pricing for GitHub Copilot</a></span>'
            f'<span class="source-item">Model Scores: Data from <a href="{leaderboard_url}" target="_blank" rel="noopener noreferrer">BenchLM.ai</a></span>'
        ),
        "UPDATED": f"Updated: {updated_at}",
        "TABLE": render_static_table(payload.get("columns", []), rows),
        "CHANGELOG": render_static_changelog(payload.get("changelog", [])),
    }
    for name, content in regions.items():
        start_marker = f"<!-- STATIC:{name}:START -->"
        end_marker = f"<!-- STATIC:{name}:END -->"
        if template.count(start_marker) != 1 or template.count(end_marker) != 1:
            raise RuntimeError(f"Expected one pair of static {name} markers in index.html.")
        start = template.index(start_marker) + len(start_marker)
        end = template.index(end_marker, start)
        template = template[:start] + content + template[end:]
    return template


def write_text(path: Path, text: str) -> None:
    # Replace atomically: a killed run must not leave a truncated index.html behind.
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split()).strip()


@dataclass
class ParsedTable:
    heading: str
    rows: list[list[str]] = field(default_factory=list)


class PricingTableParser(HTMLParser):
    """Extract table rows from rendered article HTML with nearest heading."""

    def __init__(self) -> None:
        super().__init__()
        self._last_heading = ""
        self._current_heading_text = ""
        self._heading_tag = ""

        self._in_table = False
        self._current_table: ParsedTable | None = None
        self._in_row = False
        self._current_row: list[str] = []
        self._in_cell = False
        self._cell_tag = ""
        self._cell_text = ""
        self._ignored_depth = 0

        self.tables: list[ParsedTable] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._ignored_depth:
            if tag not in VOID_ELEMENTS:
                self._ignored_depth += 1
            return
        if tag == "sup":
            self._ignored_depth = 1
            return
        if tag in {"h2", "h3"}:
            self._heading_tag = tag
            self._current_heading_text = ""
            return

        if tag == "table":
            self._in_table = True
            self._current_table = ParsedTable(heading=self._last_heading)
            return

        if self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
            return

        if self._in_row and tag in {"th", "td"}:
            self._in_cell = True
            self._cell_tag = tag
            self._cell_text = ""
            return

        if self._in_cell and tag == "br":
            self._cell_text += " / "

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._heading_tag and tag == self._heading_tag:
            self._last_heading = normalize_whitespace(self._current_heading_text)
            self._heading_tag = ""
            self._current_heading_text = ""
            return

        if self._in_cell and tag == self._cell_tag:
            self._in_cell = False
            self._current_row.append(normalize_whitespace(self._cell_text))
            self._cell_tag = ""
            self._cell_text = ""
            return

        if self._in_row and tag == "tr":
            self._in_row = False
            if any(cell for cell in self._current_row) and self._current_table is not None:
                self._current_table.rows.append(self._current_row)
            self._current_row = []
            return

        if self._in_table and tag == "table":
            self._in_table = False
            if self._current_table is not None and self._current_table.rows:
                self.tables.append(self._current_table)
            self._current_table = None

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._heading_tag:
            self._current_heading_text += data
        elif self._in_cell:
            self._cell_text += data


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "copilot-model-price-comparison/1.0"})
    # One transient failure would cost the whole day's update, so back off and retry.
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                return response.read()
        except (urllib.error.URLError, OSError) as error:
            if attempt == FETCH_RETRIES:
                raise
            print(
                f"Fetch of {url} failed ({error}); retry {attempt} of {FETCH_RETRIES - 1} "
                f"in {RETRY_DELAY_SECONDS * attempt:g}s.",
                file=sys.stderr,
            )
            time.sleep(RETRY_DELAY_SECONDS * attempt)
    raise AssertionError("unreachable")


def fetch_html(url: str) -> str:
    return fetch_url(url).decode("utf-8", errors="replace")


def fetch_json(url: str) -> dict:
    return parse_json(fetch_url(url).decode("utf-8", errors="replace"), f"JSON fetched from {url}")


def parse_json(text: str, context: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{context} is not valid JSON: {exc}") from exc


def model_key(value: str, keep_parenthetical: bool = False) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    value = (
        re.sub(r"\(([^)]*)\)", r" \1 ", value)
        if keep_parenthetical
        else re.sub(r"\([^)]*\)", " ", value)
    )
    return re.sub(r"[^a-z0-9]+", "", value)


def base_model_key(value: str) -> str:
    value = model_key(value)
    return re.sub(r"(fastmode|preview|adaptive|high|max|reasoning|thinking)$", "", value)


def match_leaderboard_model(model: str, leaderboard: list[dict]) -> dict | None:
    # Most specific first: some pricing rows qualify the model in parentheses, and that
    # qualifier is part of the leaderboard name too ("GPT-5 mini (preview)" ~ "GPT-5 mini preview").
    tiers: list[tuple[str, Any, bool]] = [
        (model_key(model, keep_parenthetical=True), model_key, False),
        (model_key(model), model_key, False),
        (base_model_key(model), base_model_key, True),
    ]
    for target, key_fn, unique_only in tiers:
        if not target:
            continue
        matches = [item for item in leaderboard if key_fn(item["model"]) == target]
        if matches and (len(matches) == 1 or not unique_only):
            return matches[0]
    return None


def extract_rendered_page(html: str) -> str:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError("Could not find __NEXT_DATA__ JSON in source page.")

    data = parse_json(match.group(1), "The __NEXT_DATA__ payload of the source page")
    try:
        return data["props"]["pageProps"]["articleContext"]["renderedPage"]
    except KeyError as exc:
        raise RuntimeError("Unexpected __NEXT_DATA__ shape; renderedPage is missing.") from exc


def merge_price_columns(item: dict[str, str]) -> None:
    sums: dict[str, float] = {}
    for source, target in MERGE_COLUMNS.items():
        value = item.pop(source, "")
        if normalize_whitespace(value):
            label = f"{item.get('Model', '')} {source}"
            sums[target] = sums.get(target, 0.0) + parse_price(value, label)
    for target, total in sums.items():
        label = f"{item.get('Model', '')} {target}"
        total += parse_price(item.get(target, ""), label)
        item[target] = f"${total:.3f}".rstrip("0").rstrip(".")


def parse_tables(rendered_page: str) -> list[dict[str, str]]:
    parser = PricingTableParser()
    parser.feed(rendered_page)

    rows: list[dict[str, str]] = []
    for table in parser.tables:
        if not table.rows:
            continue
        headers = table.rows[0]
        if "Model" not in headers:
            continue
        duplicates = sorted({name for name in headers if headers.count(name) > 1})
        if duplicates:
            raise RuntimeError(
                f"Table for {table.heading!r} has duplicated column header(s) {duplicates}; "
                "prices would land in the wrong columns."
            )

        for raw_row in table.rows[1:]:
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            item = {"Provider": table.heading}
            item.update(dict(zip(headers, padded)))
            merge_price_columns(item)
            rows.append(item)

    if not rows:
        raise RuntimeError("No pricing rows were extracted from the rendered page.")
    return rows


def build_columns(rows: list[dict[str, str]]) -> list[str]:
    seen = set(PREFERRED_COLUMNS) | DROP_COLUMNS
    extras = sorted({key for row in rows for key in row.keys() if key not in seen})
    return PREFERRED_COLUMNS + extras


def sort_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    def row_key(row: dict[str, Any]) -> tuple[str, ...]:
        return tuple(normalize_whitespace(row.get(column, "")).lower() for column in columns)

    return sorted(rows, key=row_key)


def parse_price(value: str, label: str = "") -> float:
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned.lower() == "not applicable":
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"Unparseable price {cleaned!r} in {label or 'unknown row'}") from None


def rank_number(value: Any) -> int | None:
    # str.isdigit() is true for '²' and friends, which int() rejects.
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def row_key(row: dict[str, Any]) -> tuple[str, ...]:
    tier = row.get("Tier", "")
    threshold = row.get("Threshold (input tokens)", "")
    # The pricing source started labeling formerly un-tiered rows as Default.
    # Treat that metadata-only change as the same pricing row.
    if not tier and not threshold:
        tier, threshold = "Default", "Not applicable"
    return row.get("Provider", ""), row.get("Model", ""), tier, threshold


def change_summary(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[str]:
    old = {row_key(row): row for row in previous}
    new = {row_key(row): row for row in current}
    changes = []

    old_models = {(row.get("Provider", ""), row["Model"]) for row in previous}
    new_models = {(row.get("Provider", ""), row["Model"]) for row in current}
    added = sorted({model for provider, model in new_models - old_models})
    removed = sorted({model for provider, model in old_models - new_models})
    if added:
        changes.append(f"New models: {', '.join(added)}")
    if removed:
        changes.append(f"Removed models: {', '.join(removed)}")

    prices = []
    for key in sorted(old.keys() & new.keys()):
        before, after = old[key].get("Total price", ""), new[key].get("Total price", "")
        if before != after:
            label = new[key]["Model"]
            tier = new[key].get("Tier", "")
            suffix = f" ({tier})" if tier else ""
            prices.append(f"{label}{suffix}: {before} → {after}")
    if prices:
        changes.append(f"Price changes: {'; '.join(prices)}")
    return changes


def changelog_date(value: str) -> str:
    return value[:10]


def render_rss(changelog: list[dict[str, Any]]) -> str:
    entries = list(reversed(changelog))
    latest_date = entries[0]["updated_at"] if entries else datetime.now(timezone.utc).date().isoformat()
    latest_datetime = datetime.fromisoformat(f"{latest_date}T00:00:00+00:00")
    items = []
    # GUIDs must stay stable when new entries are added, so number entries per date from oldest to newest.
    per_date: dict[str, int] = {}
    indexes = []
    for entry in changelog:
        date = str(entry["updated_at"])
        indexes.append(per_date.get(date, 0))
        per_date[date] = indexes[-1] + 1
    for entry, index in zip(entries, reversed(indexes)):
        date = str(entry["updated_at"])
        published = datetime.fromisoformat(f"{date}T00:00:00+00:00")
        changes = " ".join(str(change) for change in entry["changes"])
        items.append(
            f"""    <item>
      <title>{escape(f"Important changes - {date}")}</title>
      <link>{SITE_URL}/#changelog</link>
      <guid isPermaLink="false">{SITE_URL}/#changelog-{date}-{index}</guid>
      <pubDate>{format_datetime(published, usegmt=True)}</pubDate>
      <description>{escape(changes)}</description>
    </item>"""
        )
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Copilot model price comparison - Important changes</title>
    <link>{SITE_URL}</link>
    <atom:link href="{SITE_URL}/important-changes.xml" rel="self" type="application/rss+xml" />
    <description>Daily important changes to Copilot model pricing and coding rankings.</description>
    <lastBuildDate>{format_datetime(latest_datetime, usegmt=True)}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""
    return feed


def leaderboard_models(payload: dict) -> list[dict]:
    models = payload.get("models", [])
    if not models:
        raise RuntimeError(f"No leaderboard models in the {LEADERBOARD_URL} payload; coding ranks would be empty.")
    return models


def require_ranked_rows(rows: list[dict[str, Any]]) -> None:
    if not any(row.get("Coding rank") for row in rows):
        raise RuntimeError("No pricing row matched a leaderboard model; the site would hide every row.")


def normalize_rows(
    rows: list[dict[str, str]],
    columns: list[str],
    leaderboard: list[dict],
    previous_rows: dict[tuple[str, ...], dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_rows = []
    for row in rows:
        normalized: dict[str, Any] = {
            column: normalize_whitespace(row.get(column, ""))
            for column in columns
            if column not in {"Total price", "Coding rank"}
        }
        label = f"{normalized.get('Provider', '')} {normalized.get('Model', '')}"
        total = sum(
            parse_price(normalized[column], f"{label} {column}")
            for column in PRICE_SOURCE_COLUMNS
            if normalized.get(column)
        )
        normalized["Total price"] = f"${total:.3f}".rstrip("0").rstrip(".")
        match = match_leaderboard_model(normalized["Model"], leaderboard)
        normalized["Coding rank"] = str(match["rank"]) if match else ""
        normalized["_coding_model"] = match["model"] if match else ""
        normalized["_category_scores"] = match.get("categoryScores", {}) if match else {}
        previous = previous_rows.get(row_key(row), {})
        rank, previous_rank = rank_number(normalized["Coding rank"]), rank_number(previous.get("Coding rank", ""))
        normalized["_coding_rank_diff"] = rank - previous_rank if rank is not None and previous_rank is not None else ""
        normalized["_price_diffs"] = {
            column: round(parse_price(normalized.get(column, ""), f"{label} {column}") - parse_price(previous.get(column, ""), f"committed {label} {column}"), 6)
            if normalized.get(column) and previous.get(column)
            and normalized.get(column, "").lower() != "not applicable"
            and previous.get(column, "").lower() != "not applicable"
            else ""
            for column in PRICE_COLUMNS
        }
        normalized_rows.append(normalized)
    return normalized_rows


def main() -> None:
    html = fetch_html(SOURCE_URL)
    rendered_page = extract_rendered_page(html)
    parsed_rows = parse_tables(rendered_page)
    leaderboard = leaderboard_models(fetch_json(LEADERBOARD_URL))

    columns = build_columns(parsed_rows)
    previous = parse_json(OUTPUT_PATH.read_text(encoding="utf-8"), f"Committed {OUTPUT_PATH}") if OUTPUT_PATH.exists() else {}
    previous_rows = {row_key(row): row for row in previous.get("rows", [])}
    if len(previous_rows) != len(previous.get("rows", [])):
        raise RuntimeError("Two committed pricing rows share one row_key; price trends would use the wrong baseline.")
    rows = normalize_rows(parsed_rows, columns, leaderboard, previous_rows)
    rows = sort_rows(rows, columns)
    require_ranked_rows(rows)

    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    changes = change_summary(previous.get("rows", []), rows)
    changelog = [
        {
            "updated_at": changelog_date(str(entry["updated_at"])),
            "changes": entry["changes"],
        }
        for entry in previous.get("changelog", [])
    ]
    if changes:
        changelog.append({"updated_at": updated_at[:10], "changes": changes})
    changelog = changelog[-CHANGELOG_LIMIT:]

    payload = {
        "updated_at": updated_at,
        "changelog": changelog,
        "source_url": SOURCE_URL,
        "leaderboard_url": LEADERBOARD_URL,
        "columns": columns,
        "rows": rows,
    }

    # Render every output before writing any: a render failure must not consume the
    # changelog entry from models.json, or that day's change is lost forever.
    page = render_static_page(INDEX_PATH.read_text(encoding="utf-8"), payload)
    feed = render_rss(changelog)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_text(OUTPUT_PATH, json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
    write_text(RSS_PATH, feed)
    write_text(INDEX_PATH, page)
    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
