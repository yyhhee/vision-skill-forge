import { beforeEach, expect, it, vi } from "vitest";
import {
  creationExample,
  creationSignature,
  persistCreation,
  previewCreation,
} from "../../src/data/creation";
import { readSkill } from "../../src/data/skillRepository";
import { validateIssues } from "../../src/data/validation";
import { versionStorageKey } from "../../src/data/versions";
const input = {
  name: "新建测试",
  instruction: creationExample,
  mediaMode: "video_demo" as const,
};
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
it("accepts only the declared demonstration, never a heuristic paraphrase", () => {
  expect(previewCreation(input).branches).toHaveLength(2);
  for (const instruction of [
    "识别未戴安全帽的人",
    "检测黄色沙发和白色椅子",
    creationExample.replace("2人", "3人"),
    " ",
    "x".repeat(301),
  ])
    expect(() => previewCreation({ ...input, instruction })).toThrow();
  expect(localStorage.length).toBe(0);
});
it("removes seed geometry, keeps complete references and exposes only pending-region validation", () => {
  const doc = previewCreation(input);
  expect(doc.regions.every((r) => !r.saved && r.points.length === 0)).toBe(
    true,
  );
  expect(validateIssues(doc).map((i) => i.kind)).toEqual(["region", "region"]);
  expect(doc.final.members).toEqual(doc.branches.map((b) => b.id));
  expect(doc.outputs[0].source).toBe(doc.final.id);
});
it("binds previews to every editable input, including mode and name", () => {
  const signature = creationSignature(input);
  expect(creationSignature({ ...input, name: "另一个" })).not.toBe(signature);
  expect(creationSignature({ ...input, mediaMode: "image" })).not.toBe(
    signature,
  );
  expect(previewCreation({ ...input, mediaMode: "image" }).mediaMode).toBe(
    "image",
  );
  expect(() => previewCreation({ ...input, name: " " })).toThrow();
});
it("saves the exact full preview as a new unapplied identity and V1 without touching its seed", () => {
  const preview = previewCreation(input),
    before = structuredClone(preview);
  const id = persistCreation(preview),
    data = readSkill(id);
  expect(id).not.toBe(preview.id);
  expect(data.revision).toBe(0);
  expect(data.draft).toEqual({ ...before, id });
  expect(preview).toEqual(before);
  expect(
    JSON.parse(localStorage.getItem(versionStorageKey(id))!).versions[0]
      .document,
  ).toEqual(data.draft);
  expect(localStorage.getItem("vsf-frontend-workspace-v1")).toBeNull();
});
it("does not acknowledge failed storage and leaves the preview available", () => {
  const doc = previewCreation(input);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("quota");
  });
  expect(() => persistCreation(doc)).toThrow("未保存");
  expect(doc.id).toBe("creation-preview");
  expect(localStorage.length).toBe(0);
});
