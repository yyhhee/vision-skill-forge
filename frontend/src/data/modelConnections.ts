export type ModelRole = "planner" | "vision";
export type ModelConnection = {
  id: string;
  name: string;
  role: ModelRole;
  adapter: "openai-compatible" | "http-standard";
  endpoint: string;
  modelName: string;
  enabled: boolean;
  capabilities: string[];
  output: "business_draft" | "boxes_classes";
  coordinates?: "normalized" | "pixels";
  mapping?: { boxes: string; category: string; score: string };
};
export type ModelRegistry = {
  schemaVersion: 1;
  models: ModelConnection[];
  selected: Partial<Record<ModelRole, string>>;
};
export const MODEL_STORAGE_KEY = "vsf-frontend-models-v1";
export const roleNames = { planner: "编排模型", vision: "视觉模型" };
export const adapterNames = {
  "openai-compatible": "OpenAI兼容",
  "http-standard": "HTTP标准适配",
};
export const outputNames = {
  business_draft: "业务编排草稿（JSON）",
  boxes_classes: "目标框 + 类别",
};
export function emptyModel(role: ModelRole): ModelConnection {
  return {
    id: "model-" + crypto.randomUUID(),
    name: "",
    role,
    adapter: role === "planner" ? "openai-compatible" : "http-standard",
    endpoint: "",
    modelName: "",
    enabled: false,
    capabilities:
      role === "planner"
        ? ["structured_draft"]
        : ["detection", "multi_category"],
    output: role === "planner" ? "business_draft" : "boxes_classes",
    ...(role === "vision" ? { coordinates: "normalized" as const } : {}),
  };
}
export function seedModels(fixture = false): ModelRegistry {
  const make = (
    id: string,
    name: string,
    role: ModelRole,
    adapter: ModelConnection["adapter"],
    modelName = "",
  ): ModelConnection => ({
    ...emptyModel(role),
    id,
    name,
    adapter,
    modelName,
    endpoint: "",
    enabled: false,
  });
  const models = [
    make("rex-reference", "Rex-Omni", "vision", "openai-compatible"),
    make(
      "visual-demo",
      "自定义小模型",
      "vision",
      "http-standard",
      "custom-detector",
    ),
    make("local-reference", "本地检测模型", "vision", "http-standard"),
    make("planner-demo", "DeepSeek", "planner", "openai-compatible"),
  ];
  if (fixture) {
    models[0].endpoint = "https://rex.example/api";
    models[0].modelName = "rex-omni";
    models[0].enabled = true;
    models[1].endpoint = "https://your-model.example/api";
  }
  return {
    schemaVersion: 1,
    models,
    selected: fixture ? { vision: "rex-reference" } : {},
  };
}
export function validateModel(
  model: ModelConnection,
  records: ModelConnection[] = [],
  complete = true,
): string[] {
  const errors: string[] = [];
  if (!model.name.trim() || model.name.length > 80)
    errors.push("显示名称为1–80字。");
  if (
    records.some(
      (m) =>
        m.id !== model.id &&
        m.role === model.role &&
        m.name.trim() === model.name.trim(),
    )
  )
    errors.push("该用途已存在同名模型，请更换显示名称。");
  if (!model.modelName.trim() && complete)
    errors.push("请填写服务端模型名称。");
  if (model.modelName.length > 160) errors.push("模型名称不能超过160字。");
  if (!model.endpoint.trim()) {
    if (complete) errors.push("请填写服务地址。");
  } else {
    try {
      const url = new URL(model.endpoint);
      if (
        !["http:", "https:"].includes(url.protocol) ||
        url.username ||
        url.password ||
        url.search ||
        url.hash ||
        model.endpoint.includes("?") ||
        model.endpoint.includes("#") ||
        model.endpoint.length > 2048
      )
        throw new Error();
    } catch {
      errors.push(
        "服务地址须为HTTP/HTTPS完整地址，不得包含账号、密码、查询参数或片段；不要在地址中放密钥。",
      );
    }
  }
  if (
    model.role === "vision" &&
    (!model.capabilities.includes("detection") ||
      model.output !== "boxes_classes" ||
      !["normalized", "pixels"].includes(model.coordinates ?? ""))
  )
    errors.push("视觉模型须声明图像检测、目标框和类别以及坐标规范。");
  if (
    model.role === "planner" &&
    (!model.capabilities.includes("structured_draft") ||
      model.output !== "business_draft" ||
      model.mapping ||
      model.coordinates)
  )
    errors.push("编排模型须声明结构化草稿输出，不使用目标框坐标或视觉映射。");
  if (
    model.mapping &&
    Object.values(model.mapping).some(
      (v) =>
        !v ||
        v.length > 100 ||
        !/^[A-Za-z_][A-Za-z0-9_.]*$/.test(v) ||
        /(?:^|\.)(?:__proto__|prototype|constructor)(?:\.|$)/.test(v),
    )
  )
    errors.push(
      "映射仅支持字母、数字、下划线和点分隔字段名，不接受表达式或脚本。",
    );
  return errors;
}
function assertRegistry(value: unknown): asserts value is ModelRegistry {
  const obj = value as ModelRegistry;
  if (
    !obj ||
    obj.schemaVersion !== 1 ||
    !Array.isArray(obj.models) ||
    obj.models.length > 50 ||
    !obj.selected ||
    typeof obj.selected !== "object" ||
    Array.isArray(obj.selected) ||
    Object.keys(obj).some(
      (k) => !["schemaVersion", "models", "selected"].includes(k),
    )
  )
    throw new Error("模型缓存结构无效，原内容未覆盖。");
  const ids = new Set<string>();
  for (const m of obj.models) {
    if (
      !m ||
      typeof m.id !== "string" ||
      !/^[a-zA-Z0-9_.-]{1,96}$/.test(m.id) ||
      ids.has(m.id) ||
      typeof m.name !== "string" ||
      typeof m.endpoint !== "string" ||
      typeof m.modelName !== "string" ||
      typeof m.enabled !== "boolean" ||
      !["planner", "vision"].includes(m.role) ||
      !["openai-compatible", "http-standard"].includes(m.adapter) ||
      !Array.isArray(m.capabilities) ||
      m.capabilities.some(
        (c) =>
          !(
            m.role === "planner"
              ? ["structured_draft"]
              : ["detection", "multi_category"]
          ).includes(c),
      ) ||
      Object.keys(m).some(
        (k) =>
          ![
            "id",
            "name",
            "role",
            "adapter",
            "endpoint",
            "modelName",
            "enabled",
            "capabilities",
            "output",
            "coordinates",
            "mapping",
          ].includes(k),
      )
    )
      throw new Error("模型缓存字段无效或含不支持字段，原内容未覆盖。");
    if (
      m.mapping &&
      (typeof m.mapping !== "object" ||
        Object.keys(m.mapping).sort().join(",") !== "boxes,category,score" ||
        Object.values(m.mapping).some((v) => typeof v !== "string"))
    )
      throw new Error("模型映射结构无效，原内容未覆盖。");
    if (validateModel(m, obj.models, m.enabled).length)
      throw new Error("模型缓存配置无效，原内容未覆盖。");
    ids.add(m.id);
  }
  for (const [role, id] of Object.entries(obj.selected))
    if (
      !["planner", "vision"].includes(role) ||
      !obj.models.some((m) => m.id === id && m.role === role && m.enabled)
    )
      throw new Error("所选模型引用无效，原内容未覆盖。");
}
export function readModels(): { registry: ModelRegistry; raw: string | null } {
  let raw: string | null;
  try {
    raw = localStorage.getItem(MODEL_STORAGE_KEY);
  } catch {
    throw new Error("无法读取本地模型配置，未写入任何内容。");
  }
  if (raw === null) return { registry: seedModels(), raw };
  try {
    if (raw.length > 128000) throw new Error();
    const registry = JSON.parse(raw);
    assertRegistry(registry);
    return { registry, raw };
  } catch {
    throw new Error(
      "模型缓存损坏或不兼容，原内容未覆盖。请保留备份后再处理，不会自动恢复默认。",
    );
  }
}
export function writeModels(
  registry: ModelRegistry,
  expectedRaw: string | null,
): string {
  assertRegistry(registry);
  const raw = JSON.stringify(registry);
  if (raw.length > 128000) throw new Error("模型配置过大，未保存。");
  try {
    if (localStorage.getItem(MODEL_STORAGE_KEY) !== expectedRaw)
      throw new Error("conflict");
    localStorage.setItem(MODEL_STORAGE_KEY, raw);
  } catch (e) {
    if ((e as Error).message === "conflict")
      throw new Error(
        "配置已在其它页面修改，请重新载入后再编辑；未覆盖其它页面的配置。",
      );
    throw new Error("本地存储不可用或空间不足，模型配置未保存。");
  }
  return raw;
}
export function saveModel(
  registry: ModelRegistry,
  model: ModelConnection,
): ModelRegistry {
  const errors = validateModel(model, registry.models);
  if (errors.length) throw new Error(errors.join(" "));
  const next = structuredClone(registry),
    entry = structuredClone(model);
  entry.name = entry.name.trim();
  entry.endpoint = entry.endpoint.trim();
  entry.modelName = entry.modelName.trim();
  const index = next.models.findIndex((m) => m.id === entry.id);
  if (index >= 0) {
    if (next.models[index].role !== entry.role)
      throw new Error("已有模型不能改变用途，请分别新增接入配置。");
    next.models[index] = entry;
  } else {
    if (next.models.length >= 50) throw new Error("当前最多保存50个模型配置。");
    next.models.push(entry);
  }
  return next;
}
export function setModelEnabled(
  registry: ModelRegistry,
  id: string,
  enabled: boolean,
): ModelRegistry {
  const next = structuredClone(registry),
    model = next.models.find((m) => m.id === id);
  if (!model) throw new Error("模型已不存在，请重新载入。");
  if (enabled) {
    const errors = validateModel(model, next.models);
    if (errors.length) throw new Error(errors.join(" "));
  }
  model.enabled = enabled;
  if (!enabled && next.selected[model.role] === id)
    delete next.selected[model.role];
  return next;
}
export function chooseModel(
  registry: ModelRegistry,
  id: string,
): ModelRegistry {
  const next = structuredClone(registry),
    model = next.models.find((m) => m.id === id);
  if (!model || !model.enabled)
    throw new Error("请先保存完整配置并启用，再选择此模型。");
  const errors = validateModel(model, next.models);
  if (errors.length) throw new Error(errors.join(" "));
  next.selected[model.role] = id;
  return next;
}
