import type { SkillDocument, TimeRule, Validity } from "./document";
import { evidenceNeedsReview } from "./evidenceBinding";

export type ValidationIssue = {
  id: string;
  target: string;
  kind: string;
  message: string;
  detail: string;
  code?: "evidence_review";
};
export const outputTypeNames: Record<string, string> = {
  event_list: "事件列表",
  entity_set: "目标列表",
  boolean: "是否满足",
  timeline: "阶段时间线",
};
export function resultSources(doc: SkillDocument) {
  return [
    {
      id: doc.final.id,
      label: `最终判定 · ${doc.final.operator === "AND" ? "全部同时满足" : "任一满足"}`,
      types: ["event_list", "boolean"],
    },
    ...doc.branches.map((b) => ({
      id: b.id,
      label: b.name,
      types:
        b.resultType === "entity_set"
          ? ["entity_set", "boolean", "event_list"]
          : ["boolean", "event_list"],
    })),
    ...doc.groups.map((g) => ({
      id: g.id,
      label: `编排组 · ${g.name}`,
      types:
        g.operator === "SEQUENCE"
          ? ["event_list", "timeline", "boolean"]
          : ["event_list", "boolean"],
    })),
  ];
}
export function regionDependents(doc: SkillDocument, id: string) {
  return [
    ...doc.conditions
      .filter((c) => c.region === id || c.time?.scope?.source === id)
      .map((c) => c.label),
    ...doc.branches
      .filter((b) => b.time.scope?.source === id)
      .map((b) => b.name),
    ...doc.groups
      .filter((g) => g.correlation?.source === id)
      .map((g) => g.name),
  ];
}
export function validateIssues(doc: SkillDocument): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const add = (
    target: string,
    kind: string,
    message: string,
    detail = "请修正此项后重新校验；当前运行快照保持不变。",
    code?: ValidationIssue["code"],
  ) =>
    issues.push({
      id: `${kind}:${target}:${issues.length}`,
      target,
      kind,
      message,
      detail,
      ...(code ? { code } : {}),
    });
  const sourceIds = new Set([
    ...doc.entitySources.map((s) => s.id),
    ...doc.conditions.map((c) => c.id),
  ]);
  const regionIds = new Set(doc.regions.map((r) => r.id));
  const checkTime = (
    id: string,
    kind: string,
    name: string,
    time: TimeRule,
    validity?: Validity,
  ) => {
    let invalid = ![
      "immediate",
      "continuous",
      "cumulative",
      "ratio",
      "repeat",
    ].includes(time.mode);
    if (time.mode !== "immediate" && doc.mediaMode === "image") invalid = true;
    if (
      ["continuous", "cumulative"].includes(time.mode) &&
      !(time.durationSeconds! > 0)
    )
      invalid = true;
    if (
      ["continuous", "cumulative"].includes(time.mode) &&
      (!Number.isFinite(time.allowedGapSeconds ?? 0) ||
        (time.allowedGapSeconds ?? 0) < 0)
    )
      invalid = true;
    if (
      ["cumulative", "ratio", "repeat"].includes(time.mode) &&
      !(time.windowSeconds! > 0)
    )
      invalid = true;
    if (
      time.mode === "cumulative" &&
      time.durationSeconds! > time.windowSeconds!
    )
      invalid = true;
    if (time.mode === "ratio" && (!(time.fraction! > 0) || time.fraction! > 1))
      invalid = true;
    if (
      time.mode === "repeat" &&
      (!Number.isInteger(time.count) || !(time.count! > 0))
    )
      invalid = true;
    if (
      validity &&
      (!["current_frame", "hold", "until_end"].includes(validity.mode) ||
        (validity.mode === "hold" && !(validity.seconds! > 0)))
    )
      invalid = true;
    const scope = time.scope;
    if (time.mode !== "immediate" && scope) {
      if (scope.mode === "per_region" && !regionIds.has(scope.source))
        invalid = true;
      if (scope.mode === "per_entity" && !sourceIds.has(scope.source))
        invalid = true;
      if (
        scope.mode === "per_track" &&
        !doc.entitySources.some(
          (s) => s.id === scope.source && s.trackAvailable,
        )
      )
        invalid = true;
      if (
        !["per_region", "per_entity", "per_track", "global_scene"].includes(
          scope.mode,
        )
      )
        invalid = true;
    }
    if (invalid)
      add(
        id,
        kind,
        `${name}的时间配置无效。`,
        "检查模式、计时来源、时长与有效期；累计时长不能超过观察窗口，图片不能使用视频时序。",
      );
  };
  if (!doc.instruction.trim())
    add("description", "description", "请填写技能描述。");
  const allIds = [
    ...doc.regions,
    ...doc.entitySources,
    ...doc.conditions,
    ...doc.branches,
    ...doc.groups,
    doc.final,
    ...doc.outputs,
  ].map((n) => n.id);
  if (new Set(allIds).size !== allIds.length)
    add("document", "document", "存在重复身份，无法安全建立引用。");
  for (const region of doc.regions) {
    const count = region.type === "direction" ? 2 : 3;
    if (!region.saved || region.points.length < count)
      add(
        region.id,
        "region",
        `${region.name}尚未绘制并保存。`,
        "先绘制并保存这个场景资源，再判断关联条件。不会自动补画或恢复默认区域。",
      );
    if (
      region.points.some(
        (p) =>
          p.length !== 2 ||
          p.some((v) => !Number.isFinite(v) || v < 0 || v > 1),
      )
    )
      add(region.id, "region", `${region.name}的坐标超出画面。`);
    if (!region.name.trim()) add(region.id, "region", "场景资源名称不能为空。");
    if (
      region.type !== "direction" &&
      region.points.length >= 3 &&
      Math.abs(
        region.points.reduce((a, p, i) => {
          const q = region.points[(i + 1) % region.points.length];
          return a + p[0] * q[1] - q[0] * p[1];
        }, 0),
      ) < 0.00001
    )
      add(region.id, "region", `${region.name}的面积为零，请重新绘制。`);
  }
  for (const c of doc.conditions) {
    if (c.evidenceMode !== "fraction_only" && evidenceNeedsReview(doc, c))
      add(
        c.id,
        "condition",
        `${c.label}的语义证据待核对。`,
        "目标、类别、颜色或部位发生变化。自定义短语未被覆盖；请打开条件核对名称和短语，确认后才能应用。草稿可以先保存。",
        "evidence_review",
      );
    if (c.source === c.id || !sourceIds.has(c.source))
      add(c.id, "condition", `${c.label}的目标来源无效。`);
    if (
      c.region &&
      (!regionIds.has(c.region) ||
        doc.regions.find((r) => r.id === c.region)?.type === "direction")
    )
      add(c.id, "condition", `${c.label}引用的区域不存在或不是封闭区域。`);
    if (
      c.kind === "visible_color" &&
      (!Number.isFinite(c.minimumFraction) ||
        c.minimumFraction! < 0 ||
        c.minimumFraction! > 1)
    )
      add(c.id, "condition", `${c.label}的占比须为0–100%。`);
    if (
      c.kind === "visible_color" &&
      (!c.color ||
        !["all", "any", "fraction_only", "semantic_only"].includes(
          c.evidenceMode ?? "all",
        ) ||
        !c.semanticQuery?.trim())
    )
      add(c.id, "condition", `${c.label}的颜色或证据配置无效。`);
    if (c.kind === "count" && (!Number.isInteger(c.value) || c.value! < 1))
      add(c.id, "condition", "人数须为大于0的整数。");
    if (c.time) checkTime(c.id, "time", c.label, c.time, c.validity);
  }
  for (const b of doc.branches) {
    if (
      !b.logic.members.length ||
      b.logic.members.some((id) => !doc.conditions.some((c) => c.id === id))
    )
      add(b.id, "branch", `${b.name}的条件引用无效。`);
    if (
      !["AND", "OR", "NOT"].includes(b.logic.operator) ||
      (b.logic.operator === "NOT" && b.logic.members.length !== 1)
    )
      add(b.id, "branch", `${b.name}的组合方式无效。`);
    checkTime(b.id, "time", b.name, b.time, b.validity);
  }
  const memberIds = new Set([...doc.branches, ...doc.groups].map((n) => n.id));
  const visiting = new Set<string>(),
    visited = new Set<string>();
  const cycle = (id: string): boolean => {
    if (visiting.has(id)) return true;
    if (visited.has(id)) return false;
    visiting.add(id);
    const found =
      doc.groups.find((g) => g.id === id)?.members.some(cycle) ?? false;
    visiting.delete(id);
    visited.add(id);
    return found;
  };
  for (const g of doc.groups) {
    if (
      !g.members.length ||
      g.members.some((id) => !memberIds.has(id)) ||
      new Set(g.members).size !== g.members.length ||
      cycle(g.id)
    )
      add(g.id, "group", `${g.name}存在循环、自引用或无效成员。`);
    if (
      !["AND", "OR", "NOT", "SEQUENCE"].includes(g.operator) ||
      (g.operator === "NOT" && g.members.length !== 1)
    )
      add(g.id, "group", `${g.name}的基础关系与成员数量不兼容。`);
    if (
      g.operator === "SEQUENCE" &&
      (doc.mediaMode === "image" ||
        g.members.length < 2 ||
        !g.transition ||
        !["previous.start", "previous.qualified", "previous.end"].includes(
          g.transition.from,
        ) ||
        g.transition.to !== "next.start" ||
        !(g.transition.minGapSeconds >= 0) ||
        !(g.transition.maxGapSeconds >= g.transition.minGapSeconds))
    )
      add(g.id, "group", `${g.name}的顺序锚点或间隔无效。`);
    if (
      g.correlation?.mode === "per_track" &&
      !doc.entitySources.some(
        (s) => s.id === g.correlation?.source && s.trackAvailable,
      )
    )
      add(g.id, "group", `${g.name}没有可用轨迹来源。`);
    if (g.validity?.mode === "hold" && !(g.validity.seconds! > 0))
      add(g.id, "group", `${g.name}的保持时长无效。`);
  }
  if (
    !doc.final.members.length ||
    doc.final.members.some((id) => !memberIds.has(id))
  )
    add(doc.final.id, "final", "最终判定引用的分支或编排组不存在。");
  for (const o of doc.outputs) {
    const source = resultSources(doc).find((s) => s.id === o.source);
    if (!source || !source.types.includes(o.resultType))
      add(
        o.id,
        "output",
        `${o.name}的来源与事件类型不兼容。`,
        "请选择仍存在且结果类型兼容的来源。来源改变后不会静默替换输出类型。",
      );
    if (!o.name.trim()) add(o.id, "output", "输出名称不能为空。");
    if (
      !Number.isFinite(o.trigger.cooldownSeconds ?? 0) ||
      (o.trigger.cooldownSeconds ?? 0) < 0
    )
      add(o.id, "output", "触发冷却时间不能为负数。");
  }
  return issues;
}
