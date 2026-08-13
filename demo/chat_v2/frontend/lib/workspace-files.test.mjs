import assert from "node:assert/strict";
import test from "node:test";
import {
  countWorkspaceFiles,
  filterWorkspaceFiles,
  isGeneratedWorkspaceFile,
} from "./workspace-files.js";

const files = [
  { name: "sales.csv", path: "sales.csv", is_generated: false },
  { name: "report.md", path: "report.md", is_generated: true },
  { name: "chart.png", path: "generated/chart.png", is_generated: true },
  { name: "notes.txt", path: "generated/notes.txt" },
];

test("classifies generated files from backend metadata or generated paths", () => {
  assert.equal(isGeneratedWorkspaceFile(files[0]), false);
  assert.equal(isGeneratedWorkspaceFile(files[1]), true);
  assert.equal(isGeneratedWorkspaceFile(files[2]), true);
  assert.equal(isGeneratedWorkspaceFile(files[3]), true);
});

test("uploaded view never includes generated files with matching names", () => {
  const uploaded = filterWorkspaceFiles(
    [
      { name: "report.md", path: "report.md", is_generated: false },
      { name: "report.md", path: "generated/report.md", is_generated: true },
    ],
    "uploaded"
  );
  assert.deepEqual(uploaded.map((file) => file.path), ["report.md"]);
});

test("counts are mutually exclusive and exhaustive", () => {
  assert.deepEqual(countWorkspaceFiles(files), {
    uploaded: 1,
    generated: 3,
    all: 4,
  });
});
