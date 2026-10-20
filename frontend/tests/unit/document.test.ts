import { describe, expect, it } from "vitest";
import {
  applyDraft,
  clone,
  conditionLabel,
  seedWorkspace,
  updateCondition,
  validateDocument,
} from "../../src/data/document";

describe("draft and applied revision boundary", () => {
  it("keeps draft10% separate fromR3 at20%", () => {
    const data = seedWorkspace();
    expect(data.draft.conditions[1].minimumFraction).toBe(0.1);
    expect(data.applied.conditions[1].minimumFraction).toBe(0.2);
  });
  it("applies a validated immutable copy as the next revision", () => {
    const data = seedWorkspace();
    const next = applyDraft(data);
    expect(next.revision).toBe(4);
    expect(next.applied.conditions[1].minimumFraction).toBe(0.1);
    next.draft.conditions[1].minimumFraction = 0.8;
    expect(next.applied.conditions[1].minimumFraction).toBe(0.1);
    expect(data.applied.conditions[1].minimumFraction).toBe(0.2);
  });
  it("invalid coordinates cannot overwriteR3", () => {
    const data = seedWorkspace();
    data.draft.regions[0].points[0][0] = 1.3;
    expect(() => applyDraft(data)).toThrow("坐标");
    expect(data.revision).toBe(3);
  });
  it("unsaved geometry blocks apply", () => {
    const data = seedWorkspace();
    data.draft.regions[1].saved = false;
    expect(validateDocument(data.draft).join()).toContain("尚未绘制并保存");
  });
  it("rejects invalid fractions and quantities", () => {
    const doc = seedWorkspace().draft;
    doc.conditions[1].minimumFraction = Number.NaN;
    doc.conditions[4].value = 1.5;
    expect(validateDocument(doc)).toHaveLength(2);
  });
  it("rejects broken condition and output references", () => {
    const doc = seedWorkspace().draft;
    doc.branches[0].logic.members.push("missing");
    doc.outputs[0].source = "missing";
    expect(validateDocument(doc)).toHaveLength(2);
  });
  it("updates one stable condition without mutating another", () => {
    const doc = seedWorkspace().draft;
    const updated = updateCondition(doc, {
      ...doc.conditions[1],
      color: "blue",
      label: "自定义蓝色条件",
    });
    expect(conditionLabel(updated.conditions[1])).toBe("自定义蓝色条件");
    expect(doc.conditions[1].color).toBe("red");
    expect(updated.conditions[2]).toEqual(doc.conditions[2]);
  });
  it("keeps each seed independent", () => {
    const first = seedWorkspace();
    const second = seedWorkspace();
    first.draft.regions[0].points[0][0] = 0;
    expect(second.draft.regions[0].points[0][0]).toBe(0.101);
    expect(clone(second)).toEqual(second);
  });
});
