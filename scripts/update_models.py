#!/usr/bin/env python3
"""Update model pricing data from GitHub Docs into data/models.json."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Final

SOURCE_URL: Final = "https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing"
LEADERBOARD_URL: Final = "https://benchlm.ai/api/data/leaderboard?category=coding"
OUTPUT_PATH: Final = Path("data/models.json")
RSS_PATH: Final = Path("important-changes.xml")
SITE_URL: Final = "https://soypsi.github.io/copilot-model-price-comparison"
NEXT_DATA_RE: Final = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
PREFERRED_COLUMNS: Final = [
    "Provider",
    "Model",
    "Release status",
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


def fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "copilot-model-price-comparison/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "copilot-model-price-comparison/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def model_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"\([^)]*\)", " ", value)
    return re.sub(r"[^a-z0-9]+", "", value)


def base_model_key(value: str) -> str:
    value = model_key(value)
    return re.sub(r"(fastmode|preview|adaptive|high|max|reasoning|thinking)$", "", value)


def match_leaderboard_model(model: str, leaderboard: list[dict]) -> dict | None:
    target = model_key(model)
    exact = [item for item in leaderboard if model_key(item["model"]) == target]
    if exact:
        return exact[0]

    target_base = base_model_key(model)
    base_matches = [item for item in leaderboard if base_model_key(item["model"]) == target_base]
    if len(base_matches) == 1:
        return base_matches[0]

    return None


def extract_rendered_page(html: str) -> str:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError("Could not find __NEXT_DATA__ JSON in source page.")

    data = json.loads(match.group(1))
    try:
        return data["props"]["pageProps"]["articleContext"]["renderedPage"]
    except KeyError as exc:
        raise RuntimeError("Unexpected __NEXT_DATA__ shape; renderedPage is missing.") from exc


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

        for raw_row in table.rows[1:]:
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            item = {"Provider": table.heading}
            item.update(dict(zip(headers, padded)))
            rows.append(item)

    if not rows:
        raise RuntimeError("No pricing rows were extracted from the rendered page.")
    return rows


def build_columns(rows: list[dict[str, str]]) -> list[str]:
    seen = set(PREFERRED_COLUMNS)
    extras = sorted({key for row in rows for key in row.keys() if key not in seen})
    return PREFERRED_COLUMNS + extras


def sort_rows(rows: list[dict[str, str]], columns: list[str]) -> list[dict[str, str]]:
    def row_key(row: dict[str, str]) -> tuple[str, ...]:
        return tuple(normalize_whitespace(row.get(column, "")).lower() for column in columns)

    return sorted(rows, key=row_key)


def parse_price(value: str) -> float:
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned.lower() == "not applicable":
        return 0.0
    return float(cleaned)


def row_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row.get(column, "") for column in ("Provider", "Model", "Tier", "Threshold (input tokens)"))


def change_summary(previous: list[dict[str, str]], current: list[dict[str, str]]) -> list[str]:
    old = {row_key(row): row for row in previous}
    new = {row_key(row): row for row in current}
    changes = []

    added = sorted({row["Model"] for key, row in new.items() if key not in old})
    removed = sorted({row["Model"] for key, row in old.items() if key not in new})
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


def write_rss(changelog: list[dict[str, object]]) -> None:
    entries = list(reversed(changelog))
    latest_date = entries[0]["updated_at"] if entries else datetime.now(timezone.utc).date().isoformat()
    latest_datetime = datetime.fromisoformat(f"{latest_date}T00:00:00+00:00")
    items = []
    for index, entry in enumerate(entries):
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
<rss version="2.0">
  <channel>
    <title>Copilot model price comparison - Important changes</title>
    <link>{SITE_URL}</link>
    <description>Daily important changes to Copilot model pricing and coding rankings.</description>
    <lastBuildDate>{format_datetime(latest_datetime, usegmt=True)}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""
    RSS_PATH.write_text(feed, encoding="utf-8")


def normalize_rows(
    rows: list[dict[str, str]],
    columns: list[str],
    leaderboard: list[dict],
    previous_rows: dict[tuple[str, ...], dict[str, str]],
) -> list[dict[str, str]]:
    normalized_rows = []
    for row in rows:
        normalized = {
            column: normalize_whitespace(row.get(column, ""))
            for column in columns
            if column not in {"Total price", "Coding rank"}
        }
        total = sum(
            parse_price(normalized[column])
            for column in ("Input", "Cached input", "Cache write", "Output")
            if normalized.get(column)
        )
        normalized["Total price"] = f"${total:.3f}".rstrip("0").rstrip(".")
        match = match_leaderboard_model(normalized["Model"], leaderboard)
        normalized["Coding rank"] = str(match["rank"]) if match else ""
        normalized["_coding_model"] = match["model"] if match else ""
        normalized["_category_scores"] = match.get("categoryScores", {}) if match else {}
        previous_rank = previous_rows.get(row_key(row), {}).get("Coding rank", "")
        normalized["_coding_rank_previous"] = previous_rank
        normalized["_coding_rank_diff"] = (
            int(normalized["Coding rank"]) - int(previous_rank)
            if normalized["Coding rank"].isdigit() and previous_rank.isdigit()
            else ""
        )
        normalized_rows.append(normalized)
    return normalized_rows


def main() -> None:
    html = fetch_html(SOURCE_URL)
    rendered_page = extract_rendered_page(html)
    parsed_rows = parse_tables(rendered_page)
    leaderboard_payload = fetch_json(LEADERBOARD_URL)
    leaderboard = leaderboard_payload.get("models", [])

    columns = build_columns(parsed_rows)
    previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")) if OUTPUT_PATH.exists() else {}
    previous_rows = {row_key(row): row for row in previous.get("rows", [])}
    rows = normalize_rows(parsed_rows, columns, leaderboard, previous_rows)
    rows = sort_rows(rows, columns)

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

    payload = {
        "updated_at": updated_at,
        "changelog": changelog,
        "source_url": SOURCE_URL,
        "leaderboard_url": LEADERBOARD_URL,
        "columns": columns,
        "rows": rows,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    write_rss(changelog)
    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
