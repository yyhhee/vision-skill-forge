import { describe, it, expect } from "vitest";
import { seedWorkspace, clone } from "../../src/data/document";
import { versionTimeSummary } from "../../src/data/versionSummary";
import {
  createSequenceDocument,
  createEditorForm,
  applyEditorForm,
} from "../../src/data/editor";
import {
  appendVersion,
  assertVersionDocument,
  emptyArchive,
  importVersion,
  parseVersionFile,
  versionFile,
} from "../../src/data/versions";

describe("complete skill versions", () => {
  it("summarizes actual condition, branch and sequence timing instead of invented durations", () => {
    const doc = createSequenceDocument(seedWorkspace().draft);
    doc.conditions[1].time = {
      mode: "continuous",
      durationSeconds: 4,
      allowedGapSeconds: 1,
      scope: { mode: "per_entity", source: "persons" },
    };
    doc.conditions[1].validity = { mode: "hold", seconds: 6 };
    expect(versionTimeSummary(doc)).toContain(
      "连续 4 秒，允许中断 1 秒，成立后保持 6 秒",
    );
    expect(versionTimeSummary(doc)).toContain("前一步");
    expect(versionTimeSummary(seedWorkspace().draft)).toContain("无额外等待");
  });
  it("rejects lossy metadata, embedded media and configurations larger than their import limit", () => {
    const doc = seedWorkspace().draft;
    Object.assign(doc, { metadata: new Map([["a", 1]]) });
    expect(() => appendVersion(emptyArchive(doc.id), doc, "")).toThrow();
    Object.assign(doc, { metadata: "x".repeat(2 * 1024 * 1024) });
    expect(() => appendVersion(emptyArchive(doc.id), doc, "")).toThrow("2 MB");
    const embedded = seedWorkspace().draft;
    embedded.mediaRef = "blob:temporary";
    expect(() => assertVersionDocument(embedded)).toThrow("素材引用");
  });
  it("re-imports a renumbered imported version or its re-export without duplicating history", () => {
    const doc = seedWorkspace().draft;
    let source = emptyArchive(doc.id);
    for (let i = 0; i < 4; i++) source = appendVersion(source, doc, "来源版本");
    const raw = JSON.stringify(versionFile(source.versions[3]));
    const imported = importVersion(emptyArchive(doc.id), raw);
    expect(imported.selected.number).toBe(1);
    expect(imported.selected.importedFrom?.number).toBe(4);
    expect(importVersion(imported.archive, raw).duplicate).toBe(true);
    const reexported = JSON.stringify(versionFile(imported.selected));
    expect(importVersion(imported.archive, reexported).duplicate).toBe(true);
    expect(parseVersionFile("\uFEFF" + raw, doc.id).document).toEqual(doc);
  });
  it("stores an immutable complete document and adds versions without overwriting history", () => {
    const doc = createSequenceDocument(seedWorkspace().draft);
    const first = appendVersion(emptyArchive(doc.id), doc, "我的版本");
    doc.groups[0].members.reverse();
    doc.conditions[1].label = "再次修改";
    const next = appendVersion(first, doc, "第二版");
    expect(first.versions).toHaveLength(1);
    expect(next.versions.map((v) => v.number)).toEqual([1, 2]);
    expect(next.versions[0].document.groups[0].members).toEqual([
      "seq-a",
      "seq-b",
    ]);
    expect(next.versions[0].document.conditions[1].label).not.toBe("再次修改");
  });
  it("round trips nested groups, timing, outputs, geometry, settings and evidence review exactly", () => {
    let doc = createSequenceDocument(seedWorkspace().draft);
    const form = createEditorForm(doc, "a-red", "condition");
    form.part = "lower";
    doc = applyEditorForm(doc, form);
    doc.conditions[1].time = {
      mode: "continuous",
      durationSeconds: 3,
      allowedGapSeconds: 0,
      scope: { mode: "per_entity", source: "persons" },
    };
    const saved = appendVersion(emptyArchive(doc.id), doc, "完整备份")
      .versions[0];
    const result = importVersion(
      emptyArchive(doc.id),
      JSON.stringify(versionFile(saved)),
    );
    expect(result.selected.document).toEqual(doc);
    expect(result.selected.document.conditions[1].semanticBinding).toEqual(
      doc.conditions[1].semanticBinding,
    );
    expect(result.selected.document.groups[1].members).toEqual([
      "group-ab",
      "seq-c",
    ]);
  });
  it("imports an older workspace export as draft without importing its applied state", () => {
    const data = seedWorkspace();
    const result = parseVersionFile(
      JSON.stringify({
        format: "vsf-frontend-demo",
        schemaVersion: 1,
        ...data,
      }),
      data.draft.id,
    );
    expect(result.document).toEqual(data.draft);
    expect(result.document.conditions[1].minimumFraction).toBe(0.1);
  });
  it("duplicate import is idempotent and a conflicting identity cannot overwrite", () => {
    const doc = seedWorkspace().draft;
    const archive = appendVersion(emptyArchive(doc.id), doc, "测试");
    const file = versionFile(archive.versions[0]);
    expect(importVersion(archive, JSON.stringify(file)).duplicate).toBe(true);
    file.version.document.name = "冲突";
    expect(() => importVersion(archive, JSON.stringify(file))).toThrow(
      "身份冲突",
    );
    expect(archive.versions[0].document.name).toBe(doc.name);
  });
  it("rejects malformed schemas, unsupported formats, broken references and cycles", () => {
    const doc = seedWorkspace().draft;
    for (const bad of [
      "oops",
      "{}",
      JSON.stringify({
        format: "vsf-skill-document",
        schemaVersion: 999,
        document: doc,
      }),
    ])
      expect(() => parseVersionFile(bad, doc.id)).toThrow();
    const invalid = clone(doc);
    invalid.groups.push({
      id: "loop",
      name: "循环",
      operator: "AND",
      members: ["loop"],
    });
    expect(() => assertVersionDocument(invalid)).toThrow("循环");
    invalid.groups = [];
    invalid.conditions[1].source = "missing";
    expect(() => assertVersionDocument(invalid)).toThrow("来源");
  });
  it("rejects other skill identities, oversized JSON, credentials and invalid geometry", () => {
    const doc = seedWorkspace().draft;
    const file = (document: unknown) =>
      JSON.stringify({
        format: "vsf-skill-document",
        schemaVersion: 1,
        document,
      });
    expect(() => parseVersionFile(file(doc), "another-skill")).toThrow(
      "其它技能",
    );
    expect(() =>
      parseVersionFile(" ".repeat(2 * 1024 * 1024 + 1), doc.id),
    ).toThrow("2 MB");
    expect(() =>
      parseVersionFile(
        file({
          ...doc,
          runSettings: {
            ...(doc.runSettings as object),
            apiKey: "test-secret",
          },
        }),
        doc.id,
      ),
    ).toThrow("密钥");
    doc.regions[0].points[0][0] = 1.1;
    expect(() => assertVersionDocument(doc)).toThrow();
  });
  it("retains unfinished annotations and custom non-executable metadata without inventing defaults", () => {
    const doc = seedWorkspace().draft;
    doc.regions[0].saved = false;
    doc.regions[0].points = [];
    Object.assign(doc, {
      editorMetadata: { tags: ["用户备注"], custom: { enabled: true } },
    });
    const saved = appendVersion(emptyArchive(doc.id), doc, "待完成草稿")
      .versions[0];
    expect(
      parseVersionFile(JSON.stringify(versionFile(saved)), doc.id).document,
    ).toEqual(doc);
  });
});
