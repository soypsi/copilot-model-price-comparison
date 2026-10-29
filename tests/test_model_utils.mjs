import assert from "node:assert/strict";
import test from "node:test";
import {
  cachePriceValue,
  contextValue,
  priceValue,
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
