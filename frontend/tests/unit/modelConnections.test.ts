import { beforeEach, expect, it, vi } from "vitest";
import {
  chooseModel,
  emptyModel,
  MODEL_STORAGE_KEY,
  readModels,
  saveModel,
  seedModels,
  setModelEnabled,
  validateModel,
  writeModels,
} from "../../src/data/modelConnections";
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
const configured = () => ({
  ...emptyModel("vision"),
  name: "测试小模型",
  endpoint: "https://model.example/api",
  modelName: "detector-v1",
});
it("reads explicit disconnected seeds without writing storage or automatic model selection", () => {
  const { registry, raw } = readModels();
  expect(registry.models).toHaveLength(4);
  expect(registry.selected).toEqual({});
  expect(raw).toBeNull();
  expect(localStorage.length).toBe(0);
});
it("adds independent models then enables and explicitly chooses, never changes the original registry", () => {
  const registry = seedModels(),
    model = configured();
  const saved = saveModel(registry, model);
  expect(saved.models).toHaveLength(5);
  expect(() => chooseModel(saved, model.id)).toThrow("先保存");
  const next = chooseModel(setModelEnabled(saved, model.id, true), model.id);
  expect(next.selected.vision).toBe(model.id);
  expect(registry.models).toHaveLength(4);
  expect(registry.selected).toEqual({});
});
it("disabling a selected model clears only that role and does not fall back automatically", () => {
  let registry = seedModels(true);
  const id = registry.selected.vision!;
  registry = setModelEnabled(registry, id, false);
  expect(registry.selected.vision).toBeUndefined();
  expect(registry.models.find((m) => m.id === id)!.enabled).toBe(false);
  expect(registry.models).toHaveLength(4);
});
it("validates endpoints without allowing credentials, parameters, fragments, scripts or embedded data", () => {
  for (const endpoint of [
    "javascript:alert(1)",
    "file:///tmp/a",
    "data:text/plain,hello",
    "https://user:password@example.com/api",
    "https://a.example/api?token=secret",
    "https://a.example/api#secret",
    "https://a.example/api?",
  ]) {
    expect(validateModel({ ...configured(), endpoint })).not.toEqual([]);
  }
});
it("requires role-compatible outputs and safe field paths", () => {
  expect(validateModel({ ...configured(), capabilities: [] })).not.toEqual([]);
  expect(
    validateModel({
      ...configured(),
      mapping: { boxes: "boxes[0]", category: "label", score: "score" },
    }),
  ).not.toEqual([]);
  expect(
    validateModel({
      ...configured(),
      mapping: { boxes: "__proto__.x", category: "label", score: "score" },
    }),
  ).not.toEqual([]);
  const planner = {
    ...emptyModel("planner"),
    name: "编排",
    endpoint: "http://127.0.0.1:8000/v1",
    modelName: "planner",
  };
  expect(validateModel(planner)).toEqual([]);
  expect(validateModel({ ...planner, coordinates: "pixels" })).not.toEqual([]);
});
it("persists a single secret-free registry, refreshes accurately, and rejects overwriting newer state", () => {
  const next = saveModel(seedModels(), configured());
  const raw = writeModels(next, null);
  expect(readModels().registry).toEqual(next);
  expect(() => writeModels(next, null)).toThrow("其它页面");
  expect(localStorage.getItem(MODEL_STORAGE_KEY)).toBe(raw);
  expect(Object.keys(JSON.parse(raw))).toEqual([
    "schemaVersion",
    "models",
    "selected",
  ]);
});
it("damaged or credential-bearing caches are preserved rather than repaired or echoed", () => {
  for (const raw of [
    "",
    "broken",
    JSON.stringify({ ...seedModels(), credentialValue: "never-save" }),
  ]) {
    localStorage.setItem(MODEL_STORAGE_KEY, raw);
    expect(() => readModels()).toThrow("原内容未覆盖");
    expect(localStorage.getItem(MODEL_STORAGE_KEY)).toBe(raw);
  }
});
it("quota failure does not report saved or write other application keys", () => {
  const registry = seedModels();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw Error("quota");
  });
  expect(() => writeModels(registry, null)).toThrow("未保存");
  expect(localStorage.length).toBe(0);
});
it("rejects array-shaped selections rather than losing selected identities on JSON save", () => {
  const raw = JSON.stringify({ ...seedModels(), selected: [] });
  localStorage.setItem(MODEL_STORAGE_KEY, raw);
  expect(() => readModels()).toThrow("原内容未覆盖");
  expect(localStorage.getItem(MODEL_STORAGE_KEY)).toBe(raw);
});
