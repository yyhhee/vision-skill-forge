import { describe, expect, it } from "vitest";
import { applyDraft, seedWorkspace } from "../../src/data/document";
import { applyEditorForm, createEditorForm } from "../../src/data/editor";
import { validateIssues } from "../../src/data/validation";
import {
  evidenceContext,
  evidenceNeedsReview,
} from "../../src/data/evidenceBinding";
import { ruleSummary } from "../../src/data/ruleSummary";

describe("configuration consistency", () => {
  it("editing the description changes no executable rule", () => {
    const doc = seedWorkspace().draft;
    const form = createEditorForm(doc, "description", "description");
    form.instruction = "这里只是我的说明，不是重新编排";
    const next = applyEditorForm(doc, form);
    expect(next.instruction).toBe(form.instruction);
    expect(next.conditions).toEqual(doc.conditions);
    expect(next.branches).toEqual(doc.branches);
    expect(next.final).toEqual(doc.final);
    expect(next.outputs).toEqual(doc.outputs);
  });
  it("preserves custom phrases and blocks application until a changed part is reviewed", () => {
    const data = seedWorkspace();
    const form = createEditorForm(data.draft, "a-red", "condition");
    form.part = "lower";
    const next = applyEditorForm(data.draft, form);
    expect(next.conditions[1].semanticQuery).toBe(
      data.draft.conditions[1].semanticQuery,
    );
    expect(
      validateIssues(next).some((i) => i.message.includes("语义证据待核对")),
    ).toBe(true);
    expect(() => applyDraft({ ...data, draft: next })).toThrow(
      "语义证据待核对",
    );
    expect(data.revision).toBe(3);
  });
  it("persists the outstanding review across closing and reopening the form", () => {
    const doc = seedWorkspace().draft;
    const form = createEditorForm(doc, "a-red", "condition");
    form.color = "blue";
    const next = applyEditorForm(doc, form);
    const reopened = createEditorForm(next, "a-red", "condition");
    expect(
      validateIssues(applyEditorForm(next, reopened)).some((i) =>
        i.message.includes("语义证据待核对"),
      ),
    ).toBe(true);
  });
  it("an explicit confirmation clears only the current binding, and a later change requires another review", () => {
    const doc = seedWorkspace().draft;
    const form = createEditorForm(doc, "a-red", "condition");
    form.part = "lower";
    const pending = applyEditorForm(doc, form);
    const reopened = createEditorForm(pending, "a-red", "condition");
    reopened.semanticQuery = "my deliberately independent evidence";
    reopened.semanticReviewedContext = evidenceContext(
      pending,
      pending.conditions[1],
    );
    const reviewed = applyEditorForm(pending, reopened);
    expect(validateIssues(reviewed)).toEqual([]);
    expect(reviewed.conditions[1].semanticQuery).toBe(reopened.semanticQuery);
    expect(reviewed.conditions[1].semanticBinding?.reviewedContext.part).toBe(
      "lower",
    );
    const changed = createEditorForm(reviewed, "a-red", "condition");
    changed.color = "blue";
    expect(
      validateIssues(applyEditorForm(reviewed, changed)).some(
        (i) => i.code === "evidence_review",
      ),
    ).toBe(true);
  });
  it("supports generated bindings for arbitrary non-human categories and follows their input changes", () => {
    const doc = seedWorkspace().draft;
    doc.entitySources.push({
      id: "machines",
      label: "机械",
      type: "entity_set",
      category: "excavator",
      trackAvailable: false,
    });
    const form = createEditorForm(doc, "a-red", "condition");
    Object.assign(form, {
      source: "machines",
      part: "whole",
      color: "yellow",
      semanticMode: "generated",
      name: "自定义机械名称",
    });
    const next = applyEditorForm(doc, form);
    expect(next.conditions[1].semanticQuery).toBe("yellow excavator");
    expect(next.conditions[1].label).toBe("自定义机械名称");
    expect(validateIssues(next)).toEqual([]);
    const changed = createEditorForm(next, "a-red", "condition");
    changed.part = "lower";
    changed.color = "black";
    const updated = applyEditorForm(next, changed);
    expect(updated.conditions[1].semanticQuery).toBe(
      "excavator with black lower part",
    );
    expect(validateIssues(updated)).toEqual([]);
    next.entitySources.find((s) => s.id === "machines")!.category = "truck";
    expect(evidenceNeedsReview(next, next.conditions[1])).toBe(true);
  });
  it("does not ask for semantic review when only the numeric threshold changes", () => {
    const doc = seedWorkspace().draft;
    const form = createEditorForm(doc, "a-red", "condition");
    form.fraction = 35;
    expect(validateIssues(applyEditorForm(doc, form))).toEqual([]);
  });
  it("tracks a source change even when the normalized category is identical", () => {
    const doc = seedWorkspace().draft;
    doc.entitySources.push({ ...doc.entitySources[0], id: "others" });
    const form = createEditorForm(doc, "a-red", "condition");
    form.source = "others";
    const next = applyEditorForm(doc, form);
    expect(validateIssues(next).some((i) => i.code === "evidence_review")).toBe(
      true,
    );
  });
  it("preserves a pending semantic review in A-only mode and blocks when B is enabled again", () => {
    const doc = seedWorkspace().draft;
    const form = createEditorForm(doc, "a-red", "condition");
    form.part = "whole";
    form.evidenceMode = "fraction_only";
    const next = applyEditorForm(doc, form);
    expect(validateIssues(next)).toEqual([]);
    const reopened = createEditorForm(next, "a-red", "condition");
    reopened.evidenceMode = "all";
    expect(
      validateIssues(applyEditorForm(next, reopened)).some(
        (i) => i.code === "evidence_review",
      ),
    ).toBe(true);
  });
  it("reverting linked inputs clears the pending mismatch without losing the custom phrase", () => {
    const doc = seedWorkspace().draft;
    const form = createEditorForm(doc, "a-red", "condition");
    form.part = "whole";
    const next = applyEditorForm(doc, form);
    const reverted = createEditorForm(next, "a-red", "condition");
    reverted.part = "upper";
    const restored = applyEditorForm(next, reverted);
    expect(validateIssues(restored)).toEqual([]);
    expect(restored.conditions[1].semanticQuery).toBe(
      doc.conditions[1].semanticQuery,
    );
  });
  it("builds the visible summary from rules, not from editable prose", () => {
    const doc = seedWorkspace().draft;
    doc.instruction = "blue object and 999 items";
    const text = ruleSummary(doc).join("\n");
    expect(text).toContain("红色占比≥10%");
    expect(text).toContain("≥ 2");
    expect(text).not.toContain(doc.instruction);
  });
});
