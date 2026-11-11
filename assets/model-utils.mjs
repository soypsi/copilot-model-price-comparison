export function cellValue(value) {
  const text = String(value || "").trim();
  return /^not applicable$/i.test(text) ? "" : text;
}

export function contextValue(row) {
  return cellValue(row["Threshold (input tokens)"]);
}

export function priceValue(value) {
  const text = cellValue(value).replace(/[$,]/g, "");
  return /^(?:\d+(?:\.\d+)?|\.\d+)$/.test(text) ? Number(text) : null;
}

export function cachePriceValue(row) {
  const values = ["Cached input", "Cache write"]
    .map((column) => priceValue(row[column]))
    .filter((value) => value !== null);
  if (!values.length) return "";
  const total = values.reduce((sum, value) => sum + value, 0);
  return `$${total.toFixed(3).replace(/\.?0+$/, "")}`;
}

export function toggleModelSelection(selectedModels, modelId) {
  if (selectedModels.has(modelId)) {
    selectedModels.delete(modelId);
  } else if (selectedModels.size < 2) {
    selectedModels.add(modelId);
  }
}

export function slugify(value) {
  return value
    .normalize("NFKD")
    .replace(/\./g, "-")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-");
}

export function benchlmModelUrl(model) {
  return `https://benchlm.ai/models/${slugify(model)}`;
}

export function benchlmCompareUrl(firstModel, secondModel) {
  const first = slugify(firstModel);
  const second = slugify(secondModel);
  // BenchLM compares models, not pricing tiers: two tiers of one model share a slug,
  // so a same-model pair opens the model page instead of a self-comparison.
  return first === second
    ? `https://benchlm.ai/models/${first}`
    : `https://benchlm.ai/compare/${first}-vs-${second}`;
}

export function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function modelIdFor(row) {
  return `${row.Provider}::${row.Model}::${row.Tier || ""}::${row["Threshold (input tokens)"] || ""}`;
}

export function categoryLabel(category) {
  return category
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export function shortCategoryLabel(category) {
  return categoryLabel(category).split(/\s+/)[0];
}

export function categoryScoreValue(score) {
  if (score == null) return "";
  const text = String(score).trim();
  if (!text || text.toLowerCase() === "n/a") return "";
  const value = Number(text);
  return Number.isFinite(value) ? String(Math.round(value)) : text;
}

export function heatStyle(value, range, reverse = false) {
  const number = Number(value);
  if (!Number.isFinite(number) || !range) return "";
  const normalized = range[0] === range[1]
    ? 0.5
    : (Math.max(range[0], Math.min(range[1], number)) - range[0]) / (range[1] - range[0]);
  const hue = (reverse ? 1 - normalized : normalized) * 120;
  return ` style="--score-hue:${hue}deg"`;
}

export function thresholdTuple(value) {
  const text = (value || "").trim();
  if (!text || /not applicable/i.test(text)) return [3, Number.POSITIVE_INFINITY];
  const match = text.match(/^(<=|>=|<|>|≤|≥)?\s*([0-9]+(?:\.[0-9]+)?)\s*([KMB])?/i);
  if (!match) return [4, Number.POSITIVE_INFINITY];
  const op = match[1] || "=";
  const num = Number.parseFloat(match[2]);
  const unit = (match[3] || "").toUpperCase();
  const mult = unit === "K" ? 1_000 : unit === "M" ? 1_000_000 : unit === "B" ? 1_000_000_000 : 1;
  const rank = op === "<=" || op === "≤" || op === "<" ? 0 : op === "=" ? 1 : 2;
  return [rank, num * mult];
}
