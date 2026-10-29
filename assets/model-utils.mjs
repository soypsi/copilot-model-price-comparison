export function cellValue(value) {
  const text = String(value || "").trim();
  return /^not applicable$/i.test(text) ? "" : text;
}

export function contextValue(row) {
  return cellValue(row["Threshold (input tokens)"]);
}

export function priceValue(value) {
  const text = cellValue(value);
  if (!text) return null;
  const number = Number.parseFloat(text.replace("$", "").trim());
  return Number.isFinite(number) ? number : null;
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
