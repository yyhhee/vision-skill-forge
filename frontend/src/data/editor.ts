import {
  clone,
  colorNames,
  type EvidenceMode,
  type SkillDocument,
  type TimeRule,
  type OrchestrationGroup,
  type EvidenceContext,
} from "./document";
import {
  evidenceContext,
  generatedSemanticQuery,
  sameEvidenceContext,
} from "./evidenceBinding";

export type EditorForm = {
  id: string;
  kind: string;
  name: string;
  color: string;
  fraction: number;
  evidenceMode: EvidenceMode;
  count: number;
  operator: string;
  timeMode: string;
  duration: number;
  gap: number;
  instruction: string;
  source: string;
  region: string;
  part: string;
  semanticQuery: string;
  semanticMode: "custom" | "generated";
  semanticReviewedContext?: EvidenceContext;
  sameEntity: boolean;
  targetKind: string;
  targetId: string;
  window: number;
  ratio: number;
  repeats: number;
  scopeMode: string;
  scopeSource: string;
  validity: string;
  hold: number;
  members: string[];
  minGap: number;
  maxGap: number;
  anchor: string;
  resultType: string;
  trigger: string;
  cooldown: number;
  evidence: string;
  showInSummary: boolean;
};
export function createEditorForm(
  doc: SkillDocument,
  id: string,
  kind: string,
): EditorForm {
  const c = doc.conditions.find((n) => n.id === id);
  const b = doc.branches.find((n) => n.id === id);
  const g = doc.groups.find((n) => n.id === id);
  const o = doc.outputs.find((n) => n.id === id);
  const r = doc.regions.find((n) => n.id === id);
  const time = c?.time ?? b?.time ?? { mode: "immediate" };
  const validity = c?.validity ?? b?.validity ?? g?.validity;
  const region =
    c?.region ??
    doc.conditions.find((n) => b?.logic.members.includes(n.id) && n.region)
      ?.region;
  return {
    id,
    kind,
    name: c?.label ?? b?.name ?? g?.name ?? o?.name ?? r?.name ?? doc.name,
    color: c?.color ?? "red",
    fraction: Math.round((c?.minimumFraction ?? 0.1) * 100),
    evidenceMode: c?.evidenceMode ?? "all",
    count: c?.value ?? 2,
    operator: g?.operator ?? b?.logic.operator ?? doc.final.operator,
    timeMode: time.mode,
    duration: time.durationSeconds ?? 5,
    gap: time.allowedGapSeconds ?? 0.5,
    instruction: doc.instruction,
    source: c?.source ?? o?.source ?? "",
    region: region ?? "",
    part: c?.part ?? "whole",
    semanticQuery: c?.semanticQuery ?? "",
    semanticMode: c?.semanticBinding?.mode ?? "custom",
    semanticReviewedContext: c
      ? clone(c.semanticBinding?.reviewedContext ?? evidenceContext(doc, c))
      : undefined,
    sameEntity: c?.sameEntityRequired !== false,
    targetKind: c ? "condition" : "branch",
    targetId: id,
    window: time.windowSeconds ?? 10,
    ratio: (time.fraction ?? 0.8) * 100,
    repeats: time.count ?? 2,
    scopeMode:
      g?.correlation?.mode ??
      time.scope?.mode ??
      (b?.identity === "per_region" ? "per_region" : "per_entity"),
    scopeSource:
      g?.correlation?.source ??
      time.scope?.source ??
      (b?.identity === "per_region"
        ? (region ?? "")
        : (c?.source ?? b?.source ?? "persons")),
    validity: validity?.mode ?? "current_frame",
    hold: validity?.seconds ?? 5,
    members: clone(g?.members ?? b?.logic.members ?? doc.final.members),
    minGap: g?.transition?.minGapSeconds ?? 0,
    maxGap: g?.transition?.maxGapSeconds ?? 10,
    anchor: g?.transition?.from ?? "previous.end",
    resultType: o?.resultType ?? "event_list",
    trigger: o?.trigger.mode ?? "once_per_episode",
    cooldown: o?.trigger.cooldownSeconds ?? 0,
    evidence: o?.evidence ?? "best_effort",
    showInSummary: o?.showInSummary !== false,
  };
}
export function formTime(f: EditorForm): TimeRule {
  if (f.timeMode === "immediate") return { mode: "immediate" };
  const rule: TimeRule = {
    mode: f.timeMode,
    scope: { mode: f.scopeMode, source: f.scopeSource },
  };
  if (["continuous", "cumulative"].includes(f.timeMode))
    Object.assign(rule, {
      durationSeconds: f.duration,
      allowedGapSeconds: f.gap,
    });
  if (["cumulative", "ratio", "repeat"].includes(f.timeMode))
    rule.windowSeconds = f.window;
  if (f.timeMode === "ratio") rule.fraction = f.ratio / 100;
  if (f.timeMode === "repeat") rule.count = f.repeats;
  return rule;
}
export function applyEditorForm(
  doc: SkillDocument,
  f: EditorForm,
): SkillDocument {
  const next = clone(doc);
  const c = next.conditions.find((n) => n.id === f.id);
  const b = next.branches.find((n) => n.id === f.id);
  const g = next.groups.find((n) => n.id === f.id);
  const o = next.outputs.find((n) => n.id === f.id);
  if (f.kind === "description") next.instruction = f.instruction.trim();
  if (f.kind === "region") {
    const r = next.regions.find((n) => n.id === f.id);
    if (r) {
      const oldName = r.name;
      r.name = f.name.trim();
      for (const item of next.conditions)
        if (item.region === r.id && item.label === `位于${oldName}`)
          item.label = `位于${r.name}`;
    }
  }
  if (f.kind === "condition" && c) {
    c.label = f.name.trim();
    c.source = f.source;
    if (c.kind === "inside") {
      const oldRegion = doc.regions.find((r) => r.id === c.region);
      c.region = f.region;
      if (f.name === `位于${oldRegion?.name}`)
        c.label = `位于${doc.regions.find((r) => r.id === f.region)?.name ?? "待选择区域"}`;
    }
    if (c.kind === "visible_color") {
      const defaultName = `${colorNames[c.color ?? "red"]}${c.part === "upper" ? "上衣" : c.part === "lower" ? "裤子" : "属性"}`;
      if (f.name === defaultName && (f.color !== c.color || f.part !== c.part))
        c.label = `${colorNames[f.color]}${f.part === "upper" ? "上衣" : f.part === "lower" ? "裤子" : "属性"}`;
      Object.assign(c, {
        color: f.color,
        part: f.part,
        minimumFraction: f.fraction / 100,
        evidenceMode: f.evidenceMode,
        semanticQuery: f.semanticQuery,
        sameEntityRequired: f.sameEntity,
      });
      const context = evidenceContext(next, c);
      const original = doc.conditions.find((item) => item.id === c.id)!;
      const originalContext = evidenceContext(doc, original);
      const previousContext = f.semanticReviewedContext ?? originalContext;
      if (f.semanticMode === "generated") {
        c.semanticQuery = generatedSemanticQuery(context);
        c.semanticBinding = { mode: "generated", reviewedContext: context };
      } else if (
        c.semanticBinding ||
        !sameEvidenceContext(context, previousContext) ||
        !sameEvidenceContext(context, originalContext) ||
        f.semanticQuery !== original.semanticQuery
      ) {
        c.semanticBinding = {
          mode: "custom",
          reviewedContext: clone(previousContext),
        };
      }
    }
    if (c.kind === "count") c.value = f.count;
  }
  if (f.kind === "branch" && b) {
    b.name = f.name.trim();
    b.logic.operator = f.operator;
    b.logic.members = clone(f.members);
    b.time = formTime(f);
  }
  if (f.kind === "time") {
    const target =
      f.targetKind === "condition"
        ? next.conditions.find((n) => n.id === f.targetId)
        : next.branches.find((n) => n.id === f.targetId);
    if (target) {
      target.time = formTime(f);
      target.validity =
        f.validity === "hold"
          ? { mode: "hold", seconds: f.hold }
          : { mode: f.validity };
    }
  }
  if (f.kind === "group" && g) {
    g.name = f.name.trim();
    g.operator = f.operator;
    g.members = clone(f.members);
    if (f.operator === "SEQUENCE")
      g.transition = {
        from: f.anchor,
        to: "next.start",
        minGapSeconds: f.minGap,
        maxGapSeconds: f.maxGap,
      };
    else delete g.transition;
    g.correlation = { mode: f.scopeMode, source: f.scopeSource };
    g.validity =
      f.validity === "hold"
        ? { mode: "hold", seconds: f.hold }
        : { mode: f.validity };
  }
  if (f.kind === "final") {
    next.final.operator = f.operator;
    next.final.members = clone(f.members);
  }
  if (f.kind === "output" && o)
    Object.assign(o, {
      name: f.name.trim(),
      source: f.source,
      resultType: f.resultType,
      trigger: { mode: f.trigger, cooldownSeconds: f.cooldown },
      evidence: f.evidence,
      showInSummary: f.showInSummary,
    });
  return next;
}
export function createSequenceDocument(base: SkillDocument): SkillDocument {
  const doc = clone(base);
  doc.id = "sequence-demo";
  doc.name = "时序组合示例";
  doc.instruction = "（分支A → 分支B）AND 分支C，触发组合事件。";
  doc.branches = [
    {
      ...clone(base.branches[0]),
      id: "seq-a",
      name: "分支A",
      resultType: "event_list",
      logic: { operator: "AND", members: ["a-inside"] },
      time: { mode: "immediate" },
    },
    {
      ...clone(base.branches[0]),
      id: "seq-b",
      name: "分支B",
      resultType: "event_list",
      logic: { operator: "AND", members: ["a-inside"] },
      time: {
        mode: "continuous",
        durationSeconds: 5,
        allowedGapSeconds: 0,
        scope: { mode: "per_region", source: "roi-1" },
      },
    },
    { ...clone(base.branches[1]), id: "seq-c", name: "分支C" },
  ];
  doc.groups = [
    {
      id: "group-ab",
      name: "先A后B",
      operator: "SEQUENCE",
      members: ["seq-a", "seq-b"],
      correlation: { mode: "global_scene", source: "scene" },
      transition: {
        from: "previous.end",
        to: "next.start",
        minGapSeconds: 0,
        maxGapSeconds: 10,
      },
      validity: { mode: "hold", seconds: 5 },
    },
    {
      id: "group-all",
      name: "（A → B）与C同时满足",
      operator: "AND",
      members: ["group-ab", "seq-c"],
    },
  ];
  doc.final.members = ["group-all"];
  doc.outputs[0].name = "组合事件";
  return doc;
}
export function newGroup(doc: SkillDocument): OrchestrationGroup {
  return {
    id: `group-${crypto.randomUUID()}`,
    name: "新编排组",
    operator: "AND",
    members: doc.branches.slice(0, 2).map((b) => b.id),
  };
}
