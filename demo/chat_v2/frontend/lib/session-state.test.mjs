import test from "node:test";
import assert from "node:assert/strict";

import {
  appendAdditionalRequirements,
  buildSessionStorageKey,
  normalizeSessionMessages,
  toServerMessages,
  toggleSelectedPath,
} from "./session-state.js";

test("session cache keys are isolated", () => {
  assert.notEqual(buildSessionStorageKey("one"), buildSessionStorageKey("two"));
});

test("server messages restore into UI messages", () => {
  const restored = normalizeSessionMessages([
    { id: "1", role: "user", content: "hello", timestamp: "2026-01-01T00:00:00Z" },
    { id: "2", role: "assistant", content: "done" },
  ], () => new Date("2026-02-01T00:00:00Z"));
  assert.equal(restored[0].sender, "user");
  assert.equal(restored[1].sender, "ai");
  assert.equal(restored[1].timestamp.toISOString(), "2026-02-01T00:00:00.000Z");
});

test("local-only messages are excluded from server persistence", () => {
  const persisted = toServerMessages([
    { id: "welcome", sender: "ai", content: "welcome", timestamp: new Date(), localOnly: true },
    { id: "user", sender: "user", content: "analyze", timestamp: new Date() },
  ]);
  assert.equal(persisted.length, 1);
  assert.equal(persisted[0].role, "user");
});

test("selected paths update immutably", () => {
  const original = new Set(["a.csv"]);
  const added = toggleSelectedPath(original, "b.csv", true);
  const removed = toggleSelectedPath(added, "a.csv", false);
  assert.deepEqual([...original], ["a.csv"]);
  assert.deepEqual([...removed], ["b.csv"]);
});

test("additional requirements append only to the latest user message", () => {
  const original = [
    { role: "system", content: "base prompt" },
    { role: "user", content: "first" },
    { role: "assistant", content: "reply" },
    { role: "user", content: "analyze data" },
  ];
  const updated = appendAdditionalRequirements(original, "Use Chinese charts");
  assert.equal(updated[0].content, "base prompt");
  assert.equal(updated[1].content, "first");
  assert.equal(
    updated[3].content,
    "analyze data\n\n# Additional Requirements\nUse Chinese charts"
  );
  assert.equal(original[3].content, "analyze data");
});
