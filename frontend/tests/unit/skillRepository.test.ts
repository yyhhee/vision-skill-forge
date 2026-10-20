import { beforeEach, describe, expect, it, vi } from "vitest";
import { clone, seedWorkspace } from "../../src/data/document";
import { createSequenceDocument } from "../../src/data/editor";
import {
  createFromTemplate,
  deleteLocalSkill,
  installSkill,
  listLocalSkills,
  readSkill,
} from "../../src/data/skillRepository";
import { LIBRARY_KEY, workspaceKey } from "../../src/data/skillStorage";
import { draftFile, versionStorageKey } from "../../src/data/versions";
import { exampleRun, RUN_STORAGE_KEY } from "../../src/data/runs";
import { libraryEntries } from "../../src/data/libraryEntries";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
const payload = (id = "custom-inspection") => {
  const doc = createSequenceDocument(seedWorkspace().draft);
  doc.id = id;
  return JSON.stringify(draftFile(doc, "完整顺序组"));
};
describe("local skill library repository", () => {
  it("a real imported skill replaces its matching reference listing without duplicate identities", () => {
    installSkill(payload("furniture"));
    expect(
      libraryEntries().filter((entry) => entry.id === "furniture"),
    ).toHaveLength(1);
    expect(
      libraryEntries().find((entry) => entry.id === "furniture")?.origin,
    ).toBe("local");
  });
  it("reads existing skills without seeding browser data or invented histories", () => {
    expect(listLocalSkills()).toHaveLength(2);
    expect(localStorage.length).toBe(0);
  });
  it("installs arbitrary full documents as un-applied drafts preserving all nested structure", () => {
    const raw = payload();
    const expected = JSON.parse(raw).document;
    const result = installSkill(raw);
    expect(result.conflict).toBe(false);
    const saved = readSkill(expected.id);
    expect(saved.draft).toEqual(expected);
    expect(saved.revision).toBe(0);
    expect(
      JSON.parse(localStorage.getItem(versionStorageKey(expected.id))!)
        .versions[0].document,
    ).toEqual(expected);
  });
  it("requires explicit copying on identity conflicts without changing existing data", () => {
    const old = seedWorkspace();
    localStorage.setItem(workspaceKey(old.draft.id), JSON.stringify(old));
    const before = localStorage.getItem(workspaceKey(old.draft.id));
    expect(installSkill(payload(old.draft.id)).conflict).toBe(true);
    expect(localStorage.getItem(workspaceKey(old.draft.id))).toBe(before);
    const copied = installSkill(payload(old.draft.id), true);
    expect(copied.document.id).not.toBe(old.draft.id);
    expect(copied.document.groups).toEqual(
      JSON.parse(payload()).document.groups,
    );
    expect(localStorage.getItem(workspaceKey(old.draft.id))).toBe(before);
  });
  it("clones named full templates with new identity and no inherited applied revision", () => {
    const created = createFromTemplate("sequence-demo", "我的流程");
    expect(readSkill(created.document.id).revision).toBe(0);
    expect(created.document.name).toBe("我的流程");
    expect(created.document.groups).toHaveLength(2);
    expect(() => createFromTemplate("helmet", "无效模板")).toThrow();
  });
  it("removes only exact selected workspace/version keys; keeps immutable runs and tombstones identity", () => {
    const result = installSkill(payload());
    const run = exampleRun(true);
    run.snapshot = clone(result.document);
    run.resultAvailability = "not_provided";
    run.events = [];
    const archive = JSON.stringify({ schemaVersion: 1, runs: [run] });
    localStorage.setItem(RUN_STORAGE_KEY, archive);
    localStorage.setItem("unrelated", "preserve");
    deleteLocalSkill(result.document.id);
    expect(localStorage.getItem(workspaceKey(result.document.id))).toBeNull();
    expect(
      localStorage.getItem(versionStorageKey(result.document.id)),
    ).toBeNull();
    expect(localStorage.getItem(RUN_STORAGE_KEY)).toBe(archive);
    expect(localStorage.getItem("unrelated")).toBe("preserve");
    expect(() => readSkill(result.document.id)).toThrow("已删除");
    expect(installSkill(payload()).conflict).toBe(true);
    expect(installSkill(payload(), true).conflict).toBe(false);
  });
  it("blocks deletion with active or unreadable runs and preserves the workspace", () => {
    installSkill(payload());
    const run = exampleRun(false);
    run.snapshot.id = "custom-inspection";
    run.resultAvailability = "not_provided";
    run.events = [];
    localStorage.setItem(
      RUN_STORAGE_KEY,
      JSON.stringify({ schemaVersion: 1, runs: [run] }),
    );
    expect(() => deleteLocalSkill("custom-inspection")).toThrow("未结束");
    localStorage.setItem(RUN_STORAGE_KEY, "bad");
    expect(() => deleteLocalSkill("custom-inspection")).toThrow();
    expect(readSkill("custom-inspection").draft.id).toBe("custom-inspection");
  });
  it("rolls back staged version writes if workspace persistence fails", () => {
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(
      function (key, value) {
        if (key === workspaceKey("custom-inspection"))
          throw new DOMException("quota", "QuotaExceededError");
        original.call(this, key, value);
      },
    );
    expect(() => installSkill(payload())).toThrow("未保存");
    expect(
      localStorage.getItem(versionStorageKey("custom-inspection")),
    ).toBeNull();
    expect(localStorage.getItem(LIBRARY_KEY)).toBeNull();
  });
  it("rejects malformed or sensitive imports and preserves damaged catalogs", () => {
    expect(() => installSkill("{}")).toThrow();
    expect(() =>
      installSkill(payload().replace('"note":', '"apiKey":"secret","note":')),
    ).toThrow("密钥");
    localStorage.setItem(LIBRARY_KEY, "broken");
    expect(() => installSkill(payload())).toThrow();
    expect(localStorage.getItem(LIBRARY_KEY)).toBe("broken");
  });
});
