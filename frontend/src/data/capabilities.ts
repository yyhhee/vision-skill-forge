/** Declarative metadata only. No handler, script or model is loaded from a manifest. */
export type CapabilityKind = "business" | "execution" | "template";
export type CapabilityManifest = {
  format: "vsf-capability-manifest";
  schemaVersion: 1;
  id: string;
  name: string;
  kind: CapabilityKind;
  description: string;
  input: string;
  output: string;
  parameters: string[];
  uses: string[];
  plannerHint: string;
};
export type Capability = CapabilityManifest & {
  builtin: boolean;
  supporting?: boolean;
};
export type CapabilityRegistry = {
  schemaVersion: 1;
  states: Record<string, boolean>;
  custom: CapabilityManifest[];
};
export const CAPABILITY_KEY = "vsf-frontend-capabilities-v1";
export const kindNames: Record<CapabilityKind, string> = {
  business: "业务能力",
  execution: "执行能力",
  template: "组合模板",
};
const idPattern = /^[a-z][a-z0-9-]{0,63}$/;
const reserved = /^(?:__proto__|constructor|prototype)$/i;
const make = (
  id: string,
  name: string,
  kind: CapabilityKind,
  description: string,
  uses: string[] = [],
  supporting = false,
): Capability => ({
  format: "vsf-capability-manifest",
  schemaVersion: 1,
  id,
  name,
  kind,
  description,
  input: "检测目标",
  output: "目标或判断结果",
  parameters: [],
  uses,
  plannerHint: description,
  builtin: true,
  supporting,
});
export const builtinCapabilities: Capability[] = [
  make(
    "detect",
    "目标检测",
    "execution",
    "从画面中识别指定类别，输出目标框与类别。",
  ),
  {
    ...make(
      "color-review",
      "颜色复核",
      "business",
      "对同一目标的颜色测量与模型语义证据进行组合判断。",
      ["detect", "color-fraction", "same-subject"],
    ),
    output: "筛选后的同主体目标",
    parameters: ["颜色", "判断部位", "最低占比", "证据组合"],
  },
  make(
    "instance-dedup",
    "实例去重",
    "execution",
    "融合同一画面的重复实例，保留定位更好的框。",
    ["detect"],
  ),
  make(
    "temporal-composition",
    "时序组合",
    "template",
    "在视频中组合先后发生的分支，明确时间间隔与关联对象。",
    ["time-window"],
  ),
  make(
    "color-fraction",
    "筛色占比",
    "execution",
    "在目标指定部位校验颜色像素占比。",
    ["detect"],
    true,
  ),
  make(
    "same-subject",
    "同一主体归属",
    "execution",
    "把属性证据绑定回同一个基础目标，避免跨目标混用。",
    ["detect"],
    true,
  ),
  make(
    "region-membership",
    "区域归属",
    "execution",
    "判断目标是否位于用户标注的区域。",
    ["detect"],
    true,
  ),
  make(
    "count",
    "目标数量",
    "execution",
    "统计来源中的目标，按配置的数量条件判断。",
    ["detect"],
    true,
  ),
  make(
    "time-window",
    "时间判断",
    "execution",
    "按指定对象、持续时间或观察窗口判断条件。",
    [],
    true,
  ),
];
export const exampleCapability: CapabilityManifest = {
  format: "vsf-capability-manifest",
  schemaVersion: 1,
  id: "custom-patrol",
  name: "自定义区域巡检",
  kind: "template",
  description: "区域与数量能力的组合清单示例；尚未接入编译器，不可执行。",
  input: "检测目标与标注区域",
  output: "区域判断结果",
  parameters: ["区域", "目标数量"],
  uses: ["region-membership", "count"],
  plannerHint: "描述区域内目标数量的判断需求；不得绕过系统校验。",
};
export const seedCapabilities = (): CapabilityRegistry => ({
  schemaVersion: 1,
  states: { "custom-patrol": false },
  custom: [structuredClone(exampleCapability)],
});
export const catalog = (registry: CapabilityRegistry): Capability[] => [
  ...builtinCapabilities,
  ...registry.custom.map((m) => ({ ...m, builtin: false })),
];
export const enabled = (r: CapabilityRegistry, id: string) =>
  r.states[id] ?? builtinCapabilities.some((c) => c.id === id);
function check(ok: unknown, message: string): asserts ok {
  if (!ok) throw new Error(message);
}
export function assertManifest(
  value: unknown,
): asserts value is CapabilityManifest {
  check(
    !!value && typeof value === "object" && !Array.isArray(value),
    "清单必须是 JSON 对象。",
  );
  const m = value as Record<string, unknown>;
  const keys = [
    "format",
    "schemaVersion",
    "id",
    "name",
    "kind",
    "description",
    "input",
    "output",
    "parameters",
    "uses",
    "plannerHint",
  ];
  check(
    Object.keys(m).every((k) => keys.includes(k) && !reserved.test(k)),
    "清单含未知字段；不接受脚本、执行入口或密钥。",
  );
  check(
    m.format === "vsf-capability-manifest" && m.schemaVersion === 1,
    "不支持这个清单格式或版本。",
  );
  check(
    typeof m.id === "string" && idPattern.test(m.id) && !reserved.test(m.id),
    "能力标识须为小写字母开头的字母、数字、横线，最多64字。",
  );
  check(
    typeof m.kind === "string" && ["business", "execution", "template"].includes(m.kind),
    "请选择业务能力、执行能力或组合模板。",
  );
  for (const k of ["name", "description", "input", "output", "plannerHint"])
    check(
      typeof m[k] === "string" &&
        (m[k] as string).trim().length > 0 &&
        (m[k] as string).length <= (k === "name" ? 80 : 1500),
      `清单字段 ${k} 无效或过长。`,
    );
  check(
    Array.isArray(m.parameters) &&
      m.parameters.length <= 32 &&
      m.parameters.every(
        (p) => typeof p === "string" && p.trim().length > 0 && p.length <= 80,
      ),
    "可调整参数须为简短名称数组。",
  );
  check(
    Array.isArray(m.uses) &&
      m.uses.length <= 32 &&
      m.uses.every(
        (id) =>
          typeof id === "string" && idPattern.test(id) && !reserved.test(id),
      ) &&
      new Set(m.uses).size === m.uses.length,
    "依赖须为不重复的能力标识数组。",
  );
}
export function assertRegistry(
  value: unknown,
): asserts value is CapabilityRegistry {
  const r = value as CapabilityRegistry;
  check(
    !!r &&
      r.schemaVersion === 1 &&
      Array.isArray(r.custom) &&
      r.custom.length <= 200 &&
      !!r.states &&
      typeof r.states === "object" &&
      !Array.isArray(r.states) &&
      Object.keys(r).every((k) =>
        ["schemaVersion", "states", "custom"].includes(k),
      ),
    "能力缓存不兼容，原内容未覆盖。",
  );
  r.custom.forEach(assertManifest);
  const all = catalog(r),
    ids = all.map((c) => c.id);
  check(
    new Set(ids).size === ids.length,
    "能力标识重复，不能覆盖内置或已有能力。",
  );
  check(
    Object.entries(r.states).every(
      ([id, on]) =>
        ids.includes(id) && typeof on === "boolean" && !reserved.test(id),
    ),
    "能力状态缓存无效，原内容未覆盖。",
  );
  const checked = new Set<string>();
  const visit = (id: string, path = new Set<string>()) => {
    check(!path.has(id), "能力依赖存在循环。");
    if (checked.has(id)) return;
    const item = all.find((c) => c.id === id);
    check(item, `依赖能力 ${id} 未安装。`);
    item.uses.forEach((dep) => visit(dep, new Set(path).add(id)));
    checked.add(id);
  };
  ids.forEach((id) => visit(id));
}
export function parseManifest(
  raw: string,
  r: CapabilityRegistry,
): CapabilityManifest {
  check(
    new TextEncoder().encode(raw).length <= 128 * 1024,
    "清单超过128 KB，未安装。",
  );
  let value: unknown;
  try {
    value = JSON.parse(raw.replace(/^\uFEFF/, ""));
  } catch {
    throw new Error("不是有效的 JSON 清单。");
  }
  assertManifest(value);
  assertRegistry({ ...r, custom: [...r.custom, value] });
  return value;
}
export function readCapabilities(): {
  registry: CapabilityRegistry;
  raw: string | null;
} {
  const raw = localStorage.getItem(CAPABILITY_KEY);
  if (raw === null) return { registry: seedCapabilities(), raw };
  try {
    const registry: unknown = JSON.parse(raw);
    assertRegistry(registry);
    return { registry, raw };
  } catch (e) {
    throw new Error(
      `能力配置不可读取：${(e as Error).message} 原内容未覆盖，请恢复备份后重新载入。`,
    );
  }
}
export function writeCapabilities(
  r: CapabilityRegistry,
  previous: string | null,
): string {
  assertRegistry(r);
  check(
    localStorage.getItem(CAPABILITY_KEY) === previous,
    "能力配置已在其它页面修改，请重新载入；本次未覆盖。",
  );
  const raw = JSON.stringify(r);
  try {
    localStorage.setItem(CAPABILITY_KEY, raw);
  } catch {
    throw new Error("未保存：本地存储不可用或空间不足。当前选择仍保留。");
  }
  return raw;
}
export function capabilityClosure(
  r: CapabilityRegistry,
  ids: string[],
): string[] {
  const all = catalog(r),
    found = new Set<string>();
  const visit = (id: string) => {
    if (found.has(id)) return;
    found.add(id);
    all.find((c) => c.id === id)?.uses.forEach(visit);
  };
  ids.forEach(visit);
  return [...found];
}
export function toggleCapability(
  r: CapabilityRegistry,
  id: string,
  on: boolean,
): CapabilityRegistry {
  check(
    catalog(r).some((c) => c.id === id),
    "能力不存在。",
  );
  if (on) {
    const missing = capabilityClosure(r, [id]).filter(
      (dep) => dep !== id && !enabled(r, dep),
    );
    check(
      !missing.length,
      `请先启用依赖：${missing.map((dep) => catalog(r).find((c) => c.id === dep)?.name ?? dep).join("、")}。不会自动替换或启用。`,
    );
  }
  return { ...r, states: { ...r.states, [id]: on } };
}
export function removeCapability(
  r: CapabilityRegistry,
  id: string,
  references: string[],
): CapabilityRegistry {
  check(
    r.custom.some((c) => c.id === id),
    "内置能力不可删除。",
  );
  const dependent = catalog(r).filter(
    (c) => c.id !== id && capabilityClosure(r, c.uses).includes(id),
  );
  check(
    !references.length && !dependent.length,
    `能力仍被引用，不能删除：${[...references, ...dependent.map((c) => c.name)].join("、")}。`,
  );
  const next = {
    ...r,
    custom: r.custom.filter((c) => c.id !== id),
    states: Object.fromEntries(
      Object.entries(r.states).filter(([k]) => k !== id),
    ),
  };
  assertRegistry(next);
  return next;
}
