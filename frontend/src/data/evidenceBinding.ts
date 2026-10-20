import type { Condition, EvidenceContext, SkillDocument } from "./document";

// Bind to normalized inputs, not to a particular image, category or garment.
export function evidenceContext(
  doc: SkillDocument,
  c: Condition,
): EvidenceContext {
  let source = c.source;
  const visited = new Set<string>();
  while (!visited.has(source)) {
    visited.add(source);
    const condition = doc.conditions.find((item) => item.id === source);
    if (!condition) break;
    source = condition.source;
  }
  return {
    source: c.source,
    category: doc.entitySources.find((s) => s.id === source)?.category ?? "",
    color: c.color ?? "",
    part: c.part ?? "whole",
  };
}
export function sameEvidenceContext(a: EvidenceContext, b: EvidenceContext) {
  return (
    !!a &&
    !!b &&
    a.source === b.source &&
    a.category === b.category &&
    a.color === b.color &&
    a.part === b.part
  );
}
export function generatedSemanticQuery(context: EvidenceContext): string {
  if (!context.category) return "";
  return context.part === "whole"
    ? `${context.color} ${context.category}`
    : `${context.category} with ${context.color} ${context.part} part`;
}
export function evidenceNeedsReview(doc: SkillDocument, c: Condition): boolean {
  if (c.kind !== "visible_color" || !c.semanticBinding) return false;
  const context = evidenceContext(doc, c);
  return (
    !["custom", "generated"].includes(c.semanticBinding.mode) ||
    !sameEvidenceContext(context, c.semanticBinding.reviewedContext) ||
    (c.semanticBinding.mode === "generated" &&
      c.semanticQuery !== generatedSemanticQuery(context))
  );
}
