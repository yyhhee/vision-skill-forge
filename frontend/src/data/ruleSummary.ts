import { colorNames, modeNames, type SkillDocument } from "./document";

export const partNames: Record<string, string> = {
  whole: "整个目标",
  upper: "上半区域",
  lower: "下半区域",
};
// Read the document only. A free-text description is never an executable rule.
export function ruleSummary(doc: SkillDocument): string[] {
  const comparisons: Record<string, string> = {
    gte: "≥",
    gt: ">",
    lte: "≤",
    lt: "<",
    eq: "=",
  };
  const labels = new Map([
    ...doc.entitySources.map((s) => [s.id, s.label] as const),
    ...doc.conditions.map((c) => [c.id, c.label] as const),
  ]);
  const expression = (id: string, visited = new Set<string>()): string => {
    if (visited.has(id)) return "循环引用（待修正）";
    const path = new Set(visited).add(id);
    const c = doc.conditions.find((item) => item.id === id);
    if (c) {
      if (c.kind === "inside")
        return `位于${doc.regions.find((r) => r.id === c.region)?.name ?? "未选择区域"}`;
      if (c.kind === "count")
        return `${labels.get(c.source) ?? "未选择来源"}的数量 ${comparisons[c.comparison ?? "gte"] ?? c.comparison} ${c.value}`;
      if (c.kind === "visible_color")
        return `${labels.get(c.source) ?? "未选择来源"} · ${partNames[c.part ?? "whole"] ?? c.part} · ${colorNames[c.color ?? ""] ?? c.color}占比≥${Math.round((c.minimumFraction ?? 0) * 100)}%，${modeNames[c.evidenceMode ?? "all"]}，语义证据「${c.semanticQuery ?? "未配置"}」`;
      return c.label;
    }
    const b = doc.branches.find((item) => item.id === id);
    const g = doc.groups.find((item) => item.id === id);
    const node = b ? b.logic : g;
    if (!node) return "无效引用（待修正）";
    const join = node.operator === "SEQUENCE" ? " → " : ` ${node.operator} `;
    return `(${node.members.map((member) => expression(member, path)).join(join)})`;
  };
  return [
    ...doc.branches.map((b) => `${b.name}：${expression(b.id)}`),
    ...doc.groups.map((g) => `${g.name}：${expression(g.id)}`),
    `最终判定：${doc.final.members.map((id) => doc.branches.find((b) => b.id === id)?.name ?? doc.groups.find((g) => g.id === id)?.name ?? "无效引用").join(` ${doc.final.operator} `)}`,
    ...doc.outputs.map((o) => `业务输出：${o.name}`),
  ];
}
