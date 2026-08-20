import test from "node:test";
import assert from "node:assert/strict";

import {
  buildSessionStorageKey,
  isAwaitingManualContinuation,
  normalizeInteractionMode,
  normalizeSessionMessages,
  toServerMessages,
  toggleSelectedPath,
} from "./session-state.js";

test("normalizes interaction mode and detects a pending manual continuation", () => {
  assert.equal(normalizeInteractionMode("manual"), "manual");
  assert.equal(normalizeInteractionMode("unexpected"), "auto");
  assert.equal(
    isAwaitingManualContinuation({ status: "awaiting_user" }),
    true
  );
  assert.equal(isAwaitingManualContinuation({ status: "idle" }), false);
  assert.equal(isAwaitingManualContinuation(null), false);
});

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
