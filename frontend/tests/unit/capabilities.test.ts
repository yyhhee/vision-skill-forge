import { beforeEach, expect, it, vi } from "vitest";
import {
  CAPABILITY_KEY,
  assertRegistry,
  catalog,
  enabled,
  exampleCapability,
  parseManifest,
  readCapabilities,
  removeCapability,
  seedCapabilities,
  toggleCapability,
  writeCapabilities,
} from "../../src/data/capabilities";
import {
  capabilityErrors,
  requiredCapabilities,
  unavailableCapabilities,
} from "../../src/data/capabilityRequirements";
import { capabilityUsage } from "../../src/data/capabilityUsage";
import { seedWorkspace, validateDocument } from "../../src/data/document";
import {
  appendVersion,
  emptyArchive,
  versionStorageKey,
} from "../../src/data/versions";
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
const custom = () => ({ ...exampleCapability, id: "my-combination" });
it("shared dependency DAG validation is bounded rather than revisiting every path", () => {
  const r = seedCapabilities();
  for (let i = 0; i < 100; i++)
    r.custom.push({
      ...custom(),
      id: `dag-${i}`,
      uses: i < 2 ? ["detect"] : [`dag-${i - 1}`, `dag-${i - 2}`],
    });
  expect(() => assertRegistry(r)).not.toThrow();
});
it("reads five prominent entries and manageable dependencies without writing", () => {
  const loaded = readCapabilities();
  expect(catalog(loaded.registry).filter((c) => !c.supporting)).toHaveLength(5);
  expect(enabled(loaded.registry, "detect")).toBe(true);
  expect(enabled(loaded.registry, "custom-patrol")).toBe(false);
  expect(localStorage.length).toBe(0);
});
it("accepts a declarative custom manifest with known dependencies but rejects executable, duplicate, unknown, cyclic and unsafe definitions", () => {
  const r = seedCapabilities(),
    m = custom();
  expect(parseManifest(JSON.stringify(m), r)).toEqual(m);
  for (const invalid of [
    { ...m, handler: "evil.js" },
      { ...m, kind: ["execution"] },
    { ...m, apiKey: "secret" },
    { ...m, id: "detect" },
    { ...m, uses: ["missing"] },
    { ...m, uses: [m.id] },
    { ...m, uses: ["detect", "detect"] },
    { ...m, id: "constructor" },
  ])
    expect(() => parseManifest(JSON.stringify(invalid), r)).toThrow();
  expect(() =>
    parseManifest('{"__proto__":{},"format":"vsf-capability-manifest"}', r),
  ).toThrow();
  expect(() => parseManifest("x".repeat(140000), r)).toThrow("128");
  expect(() =>
    assertRegistry({ ...r, custom: [{ ...m, builtin: true }] }),
  ).toThrow();
});
it("enable checks dependencies without cascade and delete never removes builtins or referenced manifests", () => {
  const r = seedCapabilities(),
    off = toggleCapability(r, "detect", false);
  expect(enabled(r, "detect")).toBe(true);
  expect(() => toggleCapability(off, "color-review", true)).toThrow("依赖");
  expect(() => removeCapability(r, "detect", [])).toThrow("内置");
  expect(() => removeCapability(r, "custom-patrol", ["saved skill"])).toThrow(
    "引用",
  );
  const used = {
    ...r,
    custom: [...r.custom, { ...custom(), uses: ["custom-patrol"] }],
  };
  expect(() => removeCapability(used, "custom-patrol", [])).toThrow("引用");
  const next = removeCapability(r, "custom-patrol", []);
  writeCapabilities(next, null);
  expect(readCapabilities().registry.custom).toEqual([]);
});
it("guards cache corruption, incompatible states, quota and concurrent updates without replacement", () => {
  for (const raw of [
    "",
    "broken",
    '{"schemaVersion":2}',
    JSON.stringify({ ...seedCapabilities(), states: { constructor: true } }),
  ]) {
    localStorage.setItem(CAPABILITY_KEY, raw);
    expect(() => readCapabilities()).toThrow();
    expect(localStorage.getItem(CAPABILITY_KEY)).toBe(raw);
  }
  localStorage.clear();
  writeCapabilities(seedCapabilities(), null);
  expect(() => writeCapabilities(seedCapabilities(), null)).toThrow("其它页面");
  const raw = localStorage.getItem(CAPABILITY_KEY);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("quota");
  });
  expect(() => writeCapabilities(seedCapabilities(), raw)).toThrow("空间不足");
  expect(localStorage.getItem(CAPABILITY_KEY)).toBe(raw);
});
it("checks runtime availability separately from schema and preserves applied snapshot validity", () => {
  const doc = seedWorkspace().applied;
  expect(requiredCapabilities(doc)).toEqual(
    expect.arrayContaining([
      "detect",
      "color-review",
      "region-membership",
      "count",
      "instance-dedup",
    ]),
  );
  const registry = toggleCapability(seedCapabilities(), "detect", false);
  expect(unavailableCapabilities(doc, registry).join()).toContain("目标检测");
  expect(validateDocument(doc)).toEqual([]);
  writeCapabilities(registry, null);
  expect(capabilityErrors(doc).length).toBeGreaterThan(0);
  expect(capabilityErrors(doc, "04")).toEqual([]);
});
it("single evidence modes need only their own capabilities; installed enabled custom metadata remains non-executable", () => {
  const doc = seedWorkspace().applied;
  doc.conditions
    .filter((c) => c.kind === "visible_color")
    .forEach((c) => {
      c.evidenceMode = "fraction_only";
    });
  const off = toggleCapability(seedCapabilities(), "color-review", false);
  expect(unavailableCapabilities(doc, off)).toEqual([]);
  const customDoc = { ...doc, capabilityRefs: ["custom-patrol"] };
  const on = toggleCapability(seedCapabilities(), "custom-patrol", true);
  expect(unavailableCapabilities(customDoc, on).join()).toContain(
    "执行器未接入",
  );
});
it("derives actual draft/applied/saved-version usage, including custom references, and fails closed on damaged archives", () => {
  const r = seedCapabilities();
  expect(capabilityUsage("color-review", r).map((row) => row.id)).toContain(
    "regional-alert",
  );
  const doc = { ...seedWorkspace().applied, capabilityRefs: ["custom-patrol"] };
  const archive = appendVersion(emptyArchive(doc.id), doc, "custom dependency");
  localStorage.setItem(versionStorageKey(doc.id), JSON.stringify(archive));
  expect(capabilityUsage("custom-patrol", r)[0].contexts).toContain("保存 V1");
  localStorage.setItem(versionStorageKey(doc.id), "broken");
  expect(() => capabilityUsage("custom-patrol", r)).toThrow();
});
