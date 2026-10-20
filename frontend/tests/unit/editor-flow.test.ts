import { describe, expect, it } from "vitest";
import { applyDraft, clone, seedWorkspace } from "../../src/data/document";
import {
  applyEditorForm,
  createEditorForm,
  createSequenceDocument,
  formTime,
} from "../../src/data/editor";
import {
  regionDependents,
  resultSources,
  validateIssues,
} from "../../src/data/validation";
describe("shared editor document contracts", () => {
  it("region renaming updates default condition labels without changing identity or custom labels", () => {
    const doc = seedWorkspace().draft;
    const f = createEditorForm(doc, "roi-2", "region");
    f.name = "右侧作业区";
    const next = applyEditorForm(doc, f);
    expect(next.conditions.find((c) => c.id === "b-inside")?.label).toBe(
      "位于右侧作业区",
    );
    expect(next.conditions.find((c) => c.id === "b-inside")?.region).toBe(
      "roi-2",
    );
    expect(doc.regions[1].name).toBe("区域2");
  });
  it("invalid fixture contains exactly the two real repair targets", () => {
    expect(
      validateIssues(seedWorkspace("15").draft).map((i) => [i.kind, i.target]),
    ).toEqual([
      ["region", "roi-2"],
      ["output", "output-alert"],
    ]);
  });
  it.each(["immediate", "continuous", "cumulative", "ratio", "repeat"])(
    "%s serializes only the active time fields",
    (mode) => {
      const f = createEditorForm(seedWorkspace().draft, "branch-b", "time");
      f.timeMode = mode;
      const time = formTime(f);
      expect(time.mode).toBe(mode);
      if (mode === "immediate") expect(time).toEqual({ mode: "immediate" });
      if (mode === "continuous") {
        expect(time.durationSeconds).toBe(5);
        expect(time.windowSeconds).toBeUndefined();
        expect(time.fraction).toBeUndefined();
      }
      if (mode === "ratio") {
        expect(time.fraction).toBe(0.8);
        expect(time.durationSeconds).toBeUndefined();
        expect(time.count).toBeUndefined();
      }
      if (mode === "repeat") {
        expect(time.count).toBe(2);
        expect(time.durationSeconds).toBeUndefined();
      }
    },
  );
  it("condition and branch times remain independent", () => {
    const doc = seedWorkspace().draft;
    const f = createEditorForm(doc, "a-red", "time");
    f.timeMode = "continuous";
    f.duration = 3;
    const next = applyEditorForm(doc, f);
    expect(next.conditions[1].time?.durationSeconds).toBe(3);
    expect(next.branches[0].time.mode).toBe("immediate");
    expect(doc.conditions[1].time).toBeUndefined();
  });
  it("cumulative duration cannot exceed its observation window", () => {
    const doc = seedWorkspace().draft;
    doc.branches[0].time = {
      mode: "cumulative",
      durationSeconds: 12,
      windowSeconds: 10,
    };
    expect(validateIssues(doc).some((i) => i.kind === "time")).toBe(true);
  });
  it("a source without tracks cannot be assigned track identity", () => {
    const doc = seedWorkspace().draft;
    doc.branches[0].time = {
      mode: "continuous",
      durationSeconds: 5,
      scope: { mode: "per_track", source: "persons" },
    };
    expect(validateIssues(doc).some((i) => i.kind === "time")).toBe(true);
  });
  it("sequence fixture is a full valid document with reusable nested groups", () => {
    const doc = createSequenceDocument(seedWorkspace().draft);
    expect(validateIssues(doc)).toEqual([]);
    expect(doc.final.members).toEqual(["group-all"]);
    expect(doc.groups[1].members).toContain("group-ab");
  });
  it("reordering members never regenerates their identities or corrupts nested refs", () => {
    const doc = createSequenceDocument(seedWorkspace().draft);
    const f = createEditorForm(doc, "group-ab", "group");
    f.members.reverse();
    const next = applyEditorForm(doc, f);
    expect(next.groups[0].members).toEqual(["seq-b", "seq-a"]);
    expect(next.groups[1].members).toEqual(doc.groups[1].members);
    expect(doc.groups[0].members).toEqual(["seq-a", "seq-b"]);
  });
  it("group self-reference and dependency cycles are blocked without repair", () => {
    const doc = createSequenceDocument(seedWorkspace().draft);
    doc.groups[0].members.push("group-all");
    expect(validateIssues(doc).some((i) => i.message.includes("循环"))).toBe(
      true,
    );
    expect(doc.groups[0].members).toContain("group-all");
  });
  it("negative/reversed transition anchors cannot replace the applied snapshot", () => {
    const data = seedWorkspace();
    data.draft = createSequenceDocument(data.draft);
    data.draft.groups[0].transition!.minGapSeconds = 11;
    expect(() => applyDraft(data)).toThrow("顺序锚点或间隔");
    expect(data.revision).toBe(3);
  });
  it("image documents disallow sequential temporal semantics", () => {
    const doc = createSequenceDocument(seedWorkspace().draft);
    doc.mediaMode = "image";
    expect(validateIssues(doc).some((i) => i.kind === "group")).toBe(true);
  });
  it("source/type compatibility is explicit, not an automatic type rewrite", () => {
    const doc = seedWorkspace().draft;
    const f = createEditorForm(doc, "output-alert", "output");
    f.resultType = "entity_set";
    const next = applyEditorForm(doc, f);
    expect(validateIssues(next).some((i) => i.kind === "output")).toBe(true);
    expect(next.outputs[0].resultType).toBe("entity_set");
    expect(
      resultSources(doc).find((s) => s.id === "branch-a")?.types,
    ).toContain("entity_set");
  });
  it("renaming source labels keeps stable output references intact", () => {
    const doc = seedWorkspace().draft;
    doc.branches[0].name = "自定义目标分支";
    doc.outputs[0].source = doc.branches[0].id;
    expect(validateIssues(doc)).toEqual([]);
    expect(
      resultSources(doc).find((s) => s.id === doc.outputs[0].source)?.label,
    ).toBe("自定义目标分支");
  });
  it("region deletion checks all references and rejects a zero-area region", () => {
    const doc = seedWorkspace().draft;
    expect(regionDependents(doc, "roi-2")).toContain("位于区域2");
    doc.regions[1].points = [
      [0.1, 0.1],
      [0.2, 0.2],
      [0.3, 0.3],
    ];
    expect(
      validateIssues(doc).some((i) => i.message.includes("面积为零")),
    ).toBe(true);
  });
  it("an output repair preserves unrelated edits and unresolved region issue", () => {
    const doc = seedWorkspace("15").draft;
    doc.conditions[1].label = "用户的颜色条件";
    const f = createEditorForm(doc, "output-alert", "output");
    f.source = "final-and";
    const next = applyEditorForm(doc, f);
    expect(validateIssues(next)).toHaveLength(1);
    expect(next.conditions[1].label).toBe("用户的颜色条件");
    expect(next.regions[1].saved).toBe(false);
  });
});
