    import { benchlmCompareUrl, benchlmModelUrl, cachePriceValue, categoryLabel, categoryScoreValue, cellValue, contextValue, escapeHtml, heatStyle, modelIdFor, priceValue, shortCategoryLabel, thresholdTuple, toggleModelSelection } from "./model-utils.mjs";

    const state = {
      columns: [],
      rows: [],
      sortColumn: "Total price",
      sortDirection: "asc",
      filters: {
        "Coding rank": "!empty",
      },
      rankCategory: "coding",
      categoryColumns: [],
      categoryRanges: {},
      codingRankRange: null,
      totalPriceRange: null,
      selectedModels: new Set(),
    };

    const table = document.getElementById("pricing-table");
    const tableWrap = document.querySelector(".table-wrap");
    const rowCount = document.getElementById("row-count");
    const sourceEl = document.getElementById("source");
    const updatedEl = document.getElementById("updated");
    const changelogEl = document.getElementById("changelog");
    const hiddenNotice = document.getElementById("hidden-notice");
    const compareButton = document.getElementById("compare-button");
    const selectionCount = document.getElementById("selection-count");
    const rankCategorySelect = document.getElementById("rank-category");
    const compactRankColumns = window.matchMedia("(max-width: 1200px)");
    const priceColumns = new Set(["Input", "Cached input", "Cache write", "Output", "Total price"]);
    const numericColumns = new Set(["Threshold (input tokens)", ...priceColumns, "Coding rank"]);
    const shortColumnNames = new Map([
      ["Total price", "Price"],
      ["Cached input", "Cache"],
      ["Cache write", "Write"],
    ]);

    table.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof Element) || target.closest("a, button, input, select, textarea")) return;
      const row = target.closest("tbody tr[data-model-id]");
      if (row) toggleRowSelection(row);
    });

    table.addEventListener("keydown", (event) => {
      if (!(event.target instanceof HTMLTableRowElement) || !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      toggleRowSelection(event.target);
    });

    function scoreHeatStyle(score, category) {
      return categoryScoreValue(score)
        ? heatStyle(score, state.categoryRanges[category])
        : "";
    }

    function rankHeatStyle(rank) {
      return cellValue(rank) ? heatStyle(rank, state.codingRankRange, true) : "";
    }

    function totalPriceHeatStyle(row) {
      const sortColumn = effectiveColumn(state.sortColumn);
      if (sortColumn !== "Coding rank" && !categoryForColumn(sortColumn)) return "";
      const price = priceValue(row["Total price"]);
      if (price === null) return "";
      const logPrice = state.totalPriceRange?.[0] > 0 ? Math.log : Math.log1p;
      const priceRange = state.totalPriceRange?.map(logPrice) ?? null;
      return heatStyle(logPrice(price), priceRange, true);
    }

    function populateRankCategories(rows) {
      const categories = Array.from(new Set(rows.flatMap((row) =>
        Object.entries(row._category_scores || {})
          .filter(([category, score]) => category !== "coding" && categoryScoreValue(score) !== "")
          .map(([category]) => category)
      )));
      state.categoryColumns = categories.map((category) => `Score: ${category}`);
      state.categoryRanges = Object.fromEntries(categories.map((category) => {
        const scores = rows
          .map((row) => row._category_scores?.[category])
          .filter((score) => categoryScoreValue(score) !== "")
          .map(Number)
          .filter(Number.isFinite);
        return [category, scores.length ? [Math.min(...scores), Math.max(...scores)] : null];
      }));
      const ranks = rows
        .map((row) => cellValue(row["Coding rank"]))
        .filter(Boolean)
        .map(Number)
        .filter(Number.isFinite);
      state.codingRankRange = ranks.length ? [Math.min(...ranks), Math.max(...ranks)] : null;
      const prices = rows.map((row) => priceValue(row["Total price"])).filter((price) => price !== null);
      state.totalPriceRange = prices.length ? [Math.min(...prices), Math.max(...prices)] : null;
      const codingOption = document.createElement("option");
      codingOption.value = "coding";
      codingOption.textContent = "Coding";
      rankCategorySelect.replaceChildren(
        codingOption,
        ...categories.map((category) => {
          const option = document.createElement("option");
          option.value = category;
          option.textContent = categoryLabel(category);
          return option;
        }),
      );
      rankCategorySelect.value = state.rankCategory;
      rankCategorySelect.closest("label").hidden = false;
    }

    function categoryForColumn(column) {
      return column.startsWith("Score: ") ? column.slice(7) : "";
    }

    function rowValue(row, column) {
      const category = categoryForColumn(column);
      if (category) return categoryScoreValue(row._category_scores?.[category]);
      if (
        column === "Coding rank"
        && compactRankColumns.matches
        && state.rankCategory !== "coding"
      ) {
        return categoryScoreValue(row._category_scores?.[state.rankCategory]);
      }
      return row[column];
    }

    function isNumericColumn(column) {
      return numericColumns.has(column) || Boolean(categoryForColumn(column));
    }

    function effectiveColumn(column) {
      return column === "Coding rank"
        && compactRankColumns.matches
        && state.rankCategory !== "coding"
        ? `Score: ${state.rankCategory}`
        : column;
    }

    function rankCategoryLabel() {
      return state.rankCategory === "coding" ? "Coding" : shortCategoryLabel(state.rankCategory);
    }

    function rankCategoryValue(row) {
      return state.rankCategory === "coding"
        ? cellValue(row["Coding rank"])
        : categoryScoreValue(row._category_scores?.[state.rankCategory]);
    }

    function toComparable(column, value) {
      const text = cellValue(value);

      if (column.toLowerCase().includes("threshold")) {
        if (!text) return { kind: "text", value: "" };
        return { kind: "threshold", value: thresholdTuple(text) };
      }

      const numericValues = state.rows
        .map((row) => cellValue(rowValue(row, column)))
        .filter(Boolean);
      const numericColumn = numericValues.length > 0 && numericValues.every((item) =>
        /^\$?\s*[0-9][0-9,]*(?:\.[0-9]+)?$/.test(item)
      );
      if (numericColumn) {
        const number = priceValue(text);
        // An empty cell is not a number, so it must not satisfy a numeric filter.
        return number === null ? { kind: "text", value: "" } : { kind: "number", value: number };
      }

      return { kind: "text", value: text.toLowerCase() };
    }

    function compareRows(a, b) {
      const col = state.sortColumn;
      const dir = state.sortDirection === "asc" ? 1 : -1;
      const av = toComparable(col, rowValue(a, col));
      const bv = toComparable(col, rowValue(b, col));

      if (av.kind === "threshold" && bv.kind === "threshold") {
        if (av.value[0] !== bv.value[0]) return (av.value[0] - bv.value[0]) * dir;
        if (av.value[1] !== bv.value[1]) return (av.value[1] - bv.value[1]) * dir;
      } else if (av.kind === "number" && bv.kind === "number" && av.value !== bv.value) {
        return (av.value - bv.value) * dir;
      } else if (String(av.value) !== String(bv.value)) {
        return (String(av.value) < String(bv.value) ? -1 : 1) * dir;
      }

      for (const fallback of ["Provider", "Model", "Tier", "Threshold (input tokens)"]) {
        const left = String(a[fallback] || "").toLowerCase();
        const right = String(b[fallback] || "").toLowerCase();
        if (left !== right) return left < right ? -1 : 1;
      }
      return 0;
    }

    function filterMatches(column, row) {
      const filter = (state.filters[column] || "").trim().toLowerCase();
      if (!filter) return true;
      const value = column === "Threshold (input tokens)"
        ? contextValue(row)
        : cellValue(rowValue(row, column));
      if (filter === "!empty") return value !== "";
      const numericFilter = parseNumericFilter(filter);
      if (numericFilter) {
        const comparable = toComparable(column, rowValue(row, column));
        if (comparable.kind !== "number") return false;
        if (numericFilter.operator === ">") return comparable.value > numericFilter.number;
        if (numericFilter.operator === ">=") return comparable.value >= numericFilter.number;
        if (numericFilter.operator === "<") return comparable.value < numericFilter.number;
        if (numericFilter.operator === "<=") return comparable.value <= numericFilter.number;
        return comparable.value === numericFilter.number;
      }
      return value.toLowerCase().includes(filter);
    }

    function hiddenReasons(row) {
      const reasons = [];
      if (state.selectedModels.size === 2 && !state.selectedModels.has(modelIdFor(row))) {
        reasons.push("two-model comparison");
      }
      for (const column of [...state.columns, ...state.categoryColumns]) {
        const filter = (state.filters[column] || "").trim();
        if (filter && !filterMatches(column, row)) {
          reasons.push(`${column}: ${filter}`);
        }
      }
      return reasons;
    }

    function hiddenRows() {
      return state.rows
        .map((row) => ({ row, reasons: hiddenReasons(row) }))
        .filter(({ reasons }) => reasons.length > 0);
    }

    function filteredRows() {
      return state.rows.filter((row) => hiddenReasons(row).length === 0);
    }

    function updateHiddenNotice(hidden) {
      if (!hidden.length) {
        hiddenNotice.hidden = true;
        hiddenNotice.textContent = "";
        return;
      }

      const reasonCounts = new Map();
      for (const { reasons } of hidden) {
        for (const reason of reasons) {
          reasonCounts.set(reason, (reasonCounts.get(reason) || 0) + 1);
        }
      }
      const reasons = Array.from(reasonCounts, ([reason, count]) => `${reason} (${count})`).join(", ");
      const models = hidden.map(({ row }) => {
        const tier = row.Tier ? `, ${row.Tier}` : "";
        const threshold = row["Threshold (input tokens)"]
          ? `, ${row["Threshold (input tokens)"]}`
          : "";
        return `${row.Provider}: ${row.Model}${tier}${threshold}`;
      });
      hiddenNotice.hidden = false;
      const modelItems = models.map((model) => `<li>${escapeHtml(model)}</li>`).join("");
      hiddenNotice.innerHTML = `
        <strong>${hidden.length} model${hidden.length === 1 ? "" : "s"} hidden</strong>
        by ${escapeHtml(reasons)}. Hover or focus to list hidden models.
        <span class="hidden-models" role="tooltip">
          <strong class="hidden-models-title">Hidden models</strong>
          <ul class="hidden-models-list">${modelItems}</ul>
        </span>
      `;
    }

    function parseNumericFilter(value) {
      const match = value.match(/^(<=|>=|<|>|=)\s*\$?\s*(-?\d+(?:\.\d+)?)$/);
      if (!match) return null;
      return {
        operator: match[1],
        number: Number.parseFloat(match[2]),
      };
    }

    function priceOffset(rows, rowIndex, column) {
      const current = priceValue(rows[rowIndex][column]);
      if (current === null) return "";

      if (column === "Total price" && state.selectedModels.size === 1) {
        const selected = state.rows.find((row) => state.selectedModels.has(modelIdFor(row)));
        const baseline = selected ? priceValue(selected[column]) : null;
        if (baseline === null || baseline === 0) return "";
        const offset = ((current - baseline) / baseline) * 100;
        return `${offset >= 0 ? "+" : ""}${offset.toFixed(1)}%`;
      }

      for (let index = rowIndex - 1; index >= 0; index -= 1) {
        const previous = priceValue(rows[index][column]);
        if (previous === null) continue;
        if (previous === 0) return "";
        const offset = ((current - previous) / previous) * 100;
        return `${offset >= 0 ? "+" : ""}${offset.toFixed(1)}%`;
      }
      return "";
    }

    function priceValueMarkup(value) {
      const match = value.match(/^(\d+)(?:\.(\d+))?$/);
      if (!match) return escapeHtml(value);
      const fraction = (match[2] || "").padEnd(3, "0").slice(0, 3);
      return `<span class="price-number"><span class="price-whole">${match[1]}</span><span>.</span><span class="price-fraction">${fraction}</span></span>`;
    }

    function priceTrend(row, column) {
      const diff = row._price_diffs?.[column];
      if (typeof diff !== "number" || diff === 0) return "";
      const formatted = `${diff > 0 ? "+" : "-"}$${Math.abs(diff).toFixed(3).replace(/\.?0+$/, "")}`;
      const direction = diff > 0 ? "up" : "down";
      const arrow = diff > 0 ? "↑" : "↓";
      return `<span class="price-trend price-trend-${direction}" title="Price change: ${formatted}">${arrow}</span>`;
    }

    function renderChangelog(changelog) {
      if (!Array.isArray(changelog) || !changelog.length) return;
      const entries = changelog.slice().reverse();
      const formatEntry = (entry) => `<li><strong>${escapeHtml(String(entry.updated_at).slice(0, 10))}</strong>: ${entry.changes.map(escapeHtml).join(" ")}</li>`;
      changelogEl.innerHTML = `<h2 id="changelog-title">Important changes <a href="important-changes.xml" target="_blank" rel="noopener noreferrer" aria-label="Subscribe to important changes RSS feed">📡</a></h2><ul>${formatEntry(entries[0])}</ul>${entries.length > 1 ? `<details class="changelog-older"><summary>Older changes (${entries.length - 1})</summary><ul>${entries.slice(1).map(formatEntry).join("")}</ul></details>` : ""}`;
      changelogEl.hidden = false;
    }

    function updateChangelogSpace() {
      const older = changelogEl.querySelector(".changelog-older");
      if (!older) return;
      older.open = false;
      older.style.maxHeight = "";
      const available = tableWrap.clientHeight - table.scrollHeight;
      const summaryHeight = older.querySelector("summary").getBoundingClientRect().height;
      if (available < summaryHeight + 20) return;
      older.open = true;
      older.style.maxHeight = `${available + summaryHeight}px`;
    }

    function renderTable() {
      const rows = filteredRows().sort(compareRows);
      updateHiddenNotice(hiddenRows());
      rowCount.textContent = `${rows.length} / ${state.rows.length} rows`;
      const displayColumns = state.columns.flatMap((column) => {
        if (column === "Tier") return [];
        if (column === "Cache write" && state.columns.includes("Cached input")) return [column, "Mobile cache"];
        if (column === "Coding rank") return [column, ...state.categoryColumns];
        return [column];
      });

      const headerCells = [
        ...displayColumns.map((column) => {
        if (column === "Mobile cache") {
          return "<th class=\"mobile-cache\" title=\"Cached input and cache write prices\">Cache</th>";
        }
        const sortColumn = effectiveColumn(column);
        const active = state.sortColumn === sortColumn ? "active" : "";
        const arrow = state.sortColumn === sortColumn ? (state.sortDirection === "asc" ? "▲" : "▼") : "";
        const numeric = isNumericColumn(column) ? " numeric-column" : "";
        const category = categoryForColumn(column);
        const currencyNote = priceColumns.has(column) ? " title=\"Prices in USD\"" : "";
        const name = escapeHtml(column);
        const shortName = shortColumnNames.get(column);
        const header = category
          ? escapeHtml(shortCategoryLabel(category))
          : column === "Coding rank"
            ? `<span class="wide-rank-label">Coding</span><span class="compact-rank-label">${escapeHtml(rankCategoryLabel())}</span>`
            : column === "Threshold (input tokens)"
              ? "Context"
            : shortName
              ? `<span class="full-label">${name}</span><span class="short-label">${shortName}</span>`
              : name;
        return `<th class="${numeric.trim()}${category ? " category-score-column" : ""}" data-column="${name}"${currencyNote}><button class="sort ${active}" data-col="${name}">${header} ${arrow}</button></th>`;
        }),
      ].join("");

      const filterCells = [
        ...displayColumns.map((column) => {
        if (column === "Mobile cache") return "<th class=\"mobile-cache\"></th>";
        const value = state.filters[column] || "";
        const escapedValue = escapeHtml(value);
        const disabled = value ? "" : " disabled";
        const active = value.trim() ? " active" : "";
        const numeric = isNumericColumn(column) ? " numeric-column" : "";
        const name = escapeHtml(column);
        return `<th class="${numeric.trim()}${categoryForColumn(column) ? " category-score-column" : ""}" data-column="${name}"><div class="filter-wrap${active}"><input class="filter${active}" data-col="${name}" value="${escapedValue}" placeholder="filter" title="Filter by text, numeric comparisons like &lt;10 or &gt;=5, or !empty to exclude empty values" aria-label="Filter ${name}: text, numeric comparisons like less than 10, or !empty to exclude empty values"><button class="filter-clear${active}" type="button" data-col="${name}" aria-label="Clear ${name} filter"${disabled}>×</button></div></th>`;
        }),
      ].join("");

      const bodyRows = rows.map((row) => {
        const modelId = modelIdFor(row);
        const isSelected = state.selectedModels.has(modelId);
        const rowClass = isSelected && state.selectedModels.size === 1 ? ' class="single-selected-row"' : "";
        const cells = [
          ...displayColumns.map((column) => {
            if (column === "Mobile cache") {
              return `<td class="mobile-cache numeric-column" title="Cached input + cache write">${escapeHtml(cachePriceValue(row))}</td>`;
            }
            const category = categoryForColumn(column);
            if (category) {
              const score = row._category_scores?.[category];
              const heat = scoreHeatStyle(score, category);
              return `<td class="numeric-column category-score-column${heat ? " score-heat-cell" : ""}" data-column="${escapeHtml(column)}"${heat}>${escapeHtml(categoryScoreValue(score))}</td>`;
            }
            const val = column === "Threshold (input tokens)"
              ? contextValue(row)
              : cellValue(rowValue(row, column));
            const displayVal = priceColumns.has(column) ? val.replace(/^\$\s*/, "") : val;
            const numeric = isNumericColumn(column) ? " numeric-column" : "";
            const name = escapeHtml(column);
            const title = column === "Threshold (input tokens)" ? ` title="${escapeHtml(val)}"` : "";
            const showOffset = priceColumns.has(column) && (
              state.sortColumn === column
              || (state.sortColumn === "Coding rank" && column === "Total price")
              || (state.selectedModels.size === 1 && column === "Total price")
            );
            const offset = showOffset ? priceOffset(rows, rows.indexOf(row), column) : "";
            const priceHeat = column === "Total price" ? totalPriceHeatStyle(row) : "";
            const priceCellClass = `${numeric.trim()}${priceHeat ? " score-heat-cell" : ""}`;
            if (column === "Model") {
              const url = benchlmModelUrl(val);
              return `<td data-column="${name}"><a href="${url}" target="_blank" rel="noopener noreferrer">${escapeHtml(val)}</a></td>`;
            }
            if (column === "Coding rank" && row._coding_model) {
              const codingRank = cellValue(row["Coding rank"]);
              const categoryScores = Object.entries(row._category_scores || {});
              const scores = categoryScores
                .map(([name, score]) => `${name}: ${score ?? "n/a"}`)
                .join(" | ");
              const label = `#${codingRank} ${row._coding_model} — ${scores}`;
              const rankDiff = Number.isInteger(row._coding_rank_diff) ? row._coding_rank_diff : null;
              const trend = rankDiff === null || rankDiff === 0 ? "" : (
                rankDiff < 0
                  ? `<span class="rank-trend rank-trend-up" title="Rank change: ${rankDiff}">↑</span>`
                  : `<span class="rank-trend rank-trend-down" title="Rank change: +${rankDiff}">↓</span>`
              );
              const selectedValue = rankCategoryValue(row);
              const selectedTitle = state.rankCategory === "coding"
                ? label
                : `${categoryLabel(state.rankCategory)}: ${selectedValue}`;
              const selectedHeat = state.rankCategory !== "coding"
                && compactRankColumns.matches
                ? scoreHeatStyle(row._category_scores?.[state.rankCategory], state.rankCategory)
                : rankHeatStyle(codingRank);
              return `<td class="${numeric.trim()}${selectedHeat ? " score-heat-cell" : ""}" data-column="${name}"${selectedHeat} title="${escapeHtml(selectedTitle)}"><span class="rank-cell${state.rankCategory === "coding" ? "" : " category-selected"}"><span class="rank-main"><span class="rank-value">${escapeHtml(displayVal)}</span>${trend}</span><span class="selected-category-score">${escapeHtml(selectedValue)}</span></span></td>`;
            }
            if (priceColumns.has(column) && offset) {
              return `<td class="${priceCellClass}" data-column="${name}"${priceHeat}><div class="price-cell"><span class="price-offset">${offset}</span><span class="price-value">${priceValueMarkup(displayVal)}</span>${priceTrend(row, column)}</div></td>`;
            }
            if (priceColumns.has(column)) {
              return `<td class="${priceCellClass}" data-column="${name}"${priceHeat}><div class="price-cell"><span class="price-offset"></span><span class="price-value">${priceValueMarkup(displayVal)}</span>${priceTrend(row, column)}</div></td>`;
            }
            return `<td class="${numeric.trim()}" data-column="${name}"${title}>${escapeHtml(displayVal)}</td>`;
          }),
        ].join("");
        return `<tr data-model-id="${escapeHtml(modelId)}" tabindex="0" aria-selected="${isSelected}"${rowClass}>${cells}</tr>`;
      }).join("");

      table.innerHTML = `
        <thead>
          <tr>${headerCells}</tr>
          <tr class="filters">${filterCells}</tr>
        </thead>
        <tbody>${bodyRows}</tbody>
      `;

      table.querySelectorAll("button.sort").forEach((el) => {
        el.addEventListener("click", () => {
          const col = el.getAttribute("data-col");
          const sortColumn = effectiveColumn(col);
          if (state.sortColumn === sortColumn) {
            state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
          } else {
            state.sortColumn = sortColumn;
            state.sortDirection = "asc";
          }
          renderTable();
        });
      });

      table.querySelectorAll("input.filter").forEach((el) => {
        el.addEventListener("input", () => {
          const col = el.getAttribute("data-col");
          const selectionStart = el.selectionStart;
          const selectionEnd = el.selectionEnd;
          state.filters[col] = el.value;
          renderTable();
          const replacement = Array.from(table.querySelectorAll("input.filter"))
            .find((input) => input.getAttribute("data-col") === col);
          if (replacement) {
            replacement.focus();
            replacement.setSelectionRange(selectionStart, selectionEnd);
          }
        });
      });

      table.querySelectorAll("button.filter-clear").forEach((el) => {
        el.addEventListener("click", () => {
          const col = el.getAttribute("data-col");
          state.filters[col] = "";
          renderTable();
          const replacement = Array.from(table.querySelectorAll("input.filter"))
            .find((input) => input.getAttribute("data-col") === col);
          replacement?.focus();
        });
      });

      updateCompareControls();
      updateChangelogSpace();
    }

    function toggleRowSelection(row) {
      const modelId = row.dataset.modelId;
      if (!modelId) return;
      toggleModelSelection(state.selectedModels, modelId);
      renderTable();
    }

    function updateCompareControls() {
      const count = state.selectedModels.size;
      selectionCount.textContent = count === 2 ? "Ready to compare" : `Select ${2 - count} more model${count === 1 ? "" : "s"}`;
      compareButton.disabled = count !== 2;
    }

    compareButton.addEventListener("click", () => {
      const selected = state.rows.filter((row) => state.selectedModels.has(modelIdFor(row)));
      if (selected.length !== 2) return;
      const [first, second] = selected;
      // slugify keeps each path segment to [a-z0-9-], so this URL can never leave benchlm.ai.
      const url = benchlmCompareUrl(first.Model, second.Model);
      window.open(url, "_blank", "noopener,noreferrer");
    });

    rankCategorySelect.addEventListener("change", () => {
      state.rankCategory = rankCategorySelect.value;
      renderTable();
    });

    function fail(message) {
      const error = document.createElement("p");
      error.className = "error";
      error.textContent = message;
      tableWrap.prepend(error);
    }

    window.addEventListener("resize", updateChangelogSpace);
    // Crossing the compact breakpoint swaps which rank column is rendered, so re-render
    // to keep state.sortColumn pointing at a visible column.
    compactRankColumns.addEventListener("change", renderTable);

    async function init() {
      try {
        const response = await fetch("data/models.json", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        state.columns = data.columns || [];
        state.rows = data.rows || [];
        if (!state.columns.length || !state.rows.length) throw new Error("No columns or rows in data file.");
        populateRankCategories(state.rows);
        sourceEl.textContent = "";
        const priceItem = sourceEl.appendChild(document.createElement("span"));
        priceItem.className = "source-item";
        priceItem.textContent = "Price Source: ";
        if (/^https?:\/\//.test(data.source_url)) {
          const link = priceItem.appendChild(document.createElement("a"));
          link.href = data.source_url;
          link.target = "_blank";
          link.rel = "noreferrer";
          link.textContent = "Models and pricing for GitHub Copilot";
        }
        const scoreItem = sourceEl.appendChild(document.createElement("span"));
        scoreItem.className = "source-item";
        scoreItem.textContent = "Model Scores: Data from ";
        if (/^https?:\/\//.test(data.leaderboard_url)) {
          const credit = scoreItem.appendChild(document.createElement("a"));
          credit.href = data.leaderboard_url;
          credit.target = "_blank";
          credit.rel = "noreferrer";
          credit.textContent = "BenchLM.ai";
        }
        updatedEl.textContent = data.updated_at ? `Updated: ${data.updated_at}` : "";
        renderChangelog(data.changelog);
        renderTable();
        document.documentElement.classList.replace("no-js", "js");
      } catch (error) {
        fail(`Failed to load data/models.json: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    if (location.port === "8000" && ["localhost", "127.0.0.1", "::1"].includes(location.hostname)) {
      const reloadSource = new EventSource("/__reload");
      reloadSource.onmessage = () => location.reload();
      reloadSource.onerror = () => reloadSource.close();
    }

    init();
