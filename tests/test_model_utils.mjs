import assert from "node:assert/strict";
import test from "node:test";
import {
  benchlmCompareUrl,
  benchlmModelUrl,
  cachePriceValue,
  categoryLabel,
  categoryScoreValue,
  contextValue,
  escapeHtml,
  heatStyle,
  modelIdFor,
  priceValue,
  shortCategoryLabel,
  slugify,
  thresholdTuple,
  toggleModelSelection,
} from "../assets/model-utils.mjs";

test("Context displays the token threshold without Tier metadata", () => {
  assert.equal(contextValue({ "Threshold (input tokens)": "100K", Tier: "Long context" }), "100K");
  assert.equal(contextValue({ "Threshold (input tokens)": "Not applicable", Tier: "Default" }), "");
});

test("Cache sums available prices and handles missing values", () => {
  assert.equal(cachePriceValue({ "Cached input": "$0.01", "Cache write": "$0.125" }), "$0.135");
  assert.equal(cachePriceValue({ "Cached input": "", "Cache write": "$0.125" }), "$0.125");
  assert.equal(cachePriceValue({ "Cached input": "Not applicable", "Cache write": "" }), "");
});

test("Price parser rejects empty and non-numeric prices", () => {
  assert.equal(priceValue("$0.125"), 0.125);
  assert.equal(priceValue("Not applicable"), null);
  assert.equal(priceValue("unknown"), null);
});

test("An empty cell has no numeric value, so a numeric filter cannot match it", () => {
  assert.equal(priceValue(""), null);
  assert.equal(priceValue("   "), null);
});

test("Grouped prices parse and junk prices are not silently truncated", () => {
  assert.equal(priceValue("$1,000"), 1000);
  assert.equal(priceValue("$0.15 per 1M tokens"), null);
  assert.equal(cachePriceValue({ "Cached input": "$1,200", "Cache write": "$0.125" }), "$1200.125");
});

test("Selection toggles models and limits the set to two", () => {
  const selected = new Set();
  toggleModelSelection(selected, "one");
  toggleModelSelection(selected, "two");
  toggleModelSelection(selected, "three");
  assert.deepEqual([...selected], ["one", "two"]);

  toggleModelSelection(selected, "one");
  toggleModelSelection(selected, "three");
  assert.deepEqual([...selected], ["two", "three"]);
});

test("Slug matches the real BenchLM slug: dots become dashes, version pairs stay distinct", () => {
  assert.equal(slugify("Claude Fable 5.2"), "claude-fable-5-2");
  assert.equal(slugify("Claude Fable 5.1"), "claude-fable-5-1");
  assert.equal(slugify("MAI-Code-1.1-Flash"), "mai-code-1-1-flash");
  assert.equal(slugify("Claude  Opus 4.8 (fast mode) (preview)"), "claude-opus-4-8-fast-mode-preview");
});

test("BenchLM links use the slug of the model name", () => {
  assert.equal(benchlmModelUrl("Claude Haiku 4.5"), "https://benchlm.ai/models/claude-haiku-4-5");
  assert.equal(benchlmCompareUrl("GPT-5.6 Sol", "Grok 4.6"), "https://benchlm.ai/compare/gpt-5-6-sol-vs-grok-4-6");
});

test("Two pricing tiers of one model open the model page, never a self-comparison", () => {
  assert.equal(benchlmCompareUrl("Claude Haiku 5.5", "Claude Haiku 5.5"), "https://benchlm.ai/models/claude-haiku-5-5");
});

test("Escaping keeps the ampersand first, so an escaped entity never becomes markup", () => {
  assert.equal(escapeHtml('a & b < c > "d"'), "a &amp; b &lt; c &gt; &quot;d&quot;");
  assert.equal(escapeHtml("&lt;"), "&amp;lt;");
  assert.equal(escapeHtml("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;");
  assert.equal(escapeHtml("it's"), "it's");
});

test("Row identity keeps the two pricing tiers of one model apart", () => {
  const longContext = { Provider: "xAI", Model: "Grok 4.6", Tier: "Long context", "Threshold (input tokens)": "> 200K" };
  assert.equal(modelIdFor(longContext), "xAI::Grok 4.6::Long context::> 200K");
  assert.notEqual(modelIdFor(longContext), modelIdFor({ ...longContext, Tier: "Default", "Threshold (input tokens)": "Not applicable" }));
});

test("Category labels match the Python updater for every category in the data file", () => {
  assert.equal(categoryLabel("instructionFollowing"), "Instruction Following");
  assert.equal(categoryLabel("multimodalGrounded"), "Multimodal Grounded");
  assert.equal(shortCategoryLabel("multimodalGrounded"), "Multimodal");
  assert.equal(shortCategoryLabel("agentic"), "Agentic");
});

test("Score text drops n/a, and heat styling needs a finite value and a range", () => {
  assert.equal(categoryScoreValue(null), "");
  assert.equal(categoryScoreValue("n/a"), "");
  assert.equal(categoryScoreValue("74.02"), "74");
  assert.equal(heatStyle(5, null), "");
  assert.equal(heatStyle("x", [1, 10]), "");
  assert.equal(heatStyle(5, [7, 7]), ' style="--score-hue:60deg"');
  assert.equal(heatStyle(1, [1, 10]), ' style="--score-hue:0deg"');
  assert.equal(heatStyle(20, [1, 10]), ' style="--score-hue:120deg"');
});

test("Threshold tuples rank operators, bare numbers, not-applicable, then junk", () => {
  assert.deepEqual(thresholdTuple("≤ 200K"), [0, 200000]);
  assert.deepEqual(thresholdTuple("272000"), [1, 272000]);
  assert.deepEqual(thresholdTuple("> 100K"), [2, 100000]);
  assert.deepEqual(thresholdTuple("Not applicable"), [3, Number.POSITIVE_INFINITY]);
  assert.deepEqual(thresholdTuple(""), [3, Number.POSITIVE_INFINITY]);
  assert.deepEqual(thresholdTuple("n/a (preview)"), [4, Number.POSITIVE_INFINITY]);
});
