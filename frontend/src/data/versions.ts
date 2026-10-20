import { clone, type SkillDocument } from "./document";
import { resultSources, validateIssues } from "./validation";
import { readSettings, validateSettings } from "./runs";

export type SkillVersion = {
  id: string;
  number: number;
  createdAt: string;
  note: string;
  document: SkillDocument;
  importedFrom?: { number?: number; createdAt?: string };
};
export type VersionArchive = {
  schemaVersion: 1;
  skillId: string;
  versions: SkillVersion[];
};
export const VERSION_FILE_LIMIT = 2 * 1024 * 1024;
export const versionStorageKey = (skillId: string) =>
  `vsf-frontend-versions-v1:${encodeURIComponent(skillId)}`;
const object = (value: unknown): value is Record<string, unknown> =>
  !!value && Object.prototype.toString.call(value) === "[object Object]";
const text = (value: unknown): value is string => typeof value === "string";
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(text);
function check(
  ok: unknown,
  message = "技能文件结构不完整或字段类型无效。请使用本前端导出的完整技能 JSON。",
): asserts ok {
  if (!ok) throw new Error(message);
}
function safeJson(value: unknown, depth = 0): void {
  check(depth <= 40, "文件嵌套过深，未导入。");
  if (Array.isArray(value)) {
    check(value.length <= 2000, "文件条目过多，未导入。");
    value.forEach((v) => safeJson(v, depth + 1));
  } else if (object(value))
    for (const [key, child] of Object.entries(value)) {
      check(
        !/^(?:__proto__|prototype|constructor)$/i.test(key),
        "文件包含不安全字段，未导入。",
      );
      check(
        !/^(?:api[_-]?key|access[_-]?token|token|secret|password|authorization|credentials?)$/i.test(
          key,
        ),
        "技能文件不接受密钥、令牌或密码。请移除敏感参数后再导入。",
      );
      safeJson(child, depth + 1);
    }
  else
    check(
      value === null ||
        text(value) ||
        typeof value === "boolean" ||
        (typeof value === "number" && Number.isFinite(value)),
    );
}
function timeShape(value: unknown) {
  check(object(value) && text(value.mode));
  for (const key of [
    "durationSeconds",
    "allowedGapSeconds",
    "windowSeconds",
    "fraction",
    "count",
  ])
    if (value[key] !== undefined) check(typeof value[key] === "number");
  if (value.scope !== undefined)
    check(
      object(value.scope) && text(value.scope.mode) && text(value.scope.source),
    );
}
function validityShape(value: unknown) {
  check(object(value) && text(value.mode));
  if (value.seconds !== undefined) check(typeof value.seconds === "number");
}
export function assertVersionDocument(
  value: unknown,
): asserts value is SkillDocument {
  safeJson(value);
  check(
    object(value) && value.schemaVersion === 1,
    "不支持这个技能 Schema 版本，未导入。",
  );
  check(
    !/^(?:data:|blob:)/i.test(String(value.mediaRef)) &&
      String(value.mediaRef).length <= 2048,
    "只保存可复用的素材引用，不接受嵌入的图片、视频或临时 Blob 地址。",
  );
  check(
    text(value.id) &&
      !!value.id.trim() &&
      text(value.name) &&
      !!value.name.trim() &&
      value.name.length <= 120 &&
      text(value.instruction) &&
      text(value.mediaRef),
  );
  check(
    value.mediaMode === undefined ||
      ["image", "video_demo"].includes(String(value.mediaMode)),
  );
  for (const key of [
    "regions",
    "entitySources",
    "conditions",
    "branches",
    "groups",
    "outputs",
  ])
    check(Array.isArray(value[key]));
  const doc = value as unknown as SkillDocument;
  if (doc.capabilityRefs !== undefined)
    check(
      Array.isArray(doc.capabilityRefs) &&
        doc.capabilityRefs.length <= 100 &&
        doc.capabilityRefs.every(
          (id) => typeof id === "string" && /^[a-z][a-z0-9-]{0,63}$/.test(id),
        ),
      "能力引用格式无效。",
    );
  for (const r of doc.regions) {
    check(
      object(r) &&
        text(r.id) &&
        text(r.name) &&
        text(r.colorIdentity) &&
        ["polygon", "rectangle", "direction"].includes(r.type) &&
        typeof r.saved === "boolean" &&
        Array.isArray(r.points),
    );
    for (const p of r.points)
      check(
        Array.isArray(p) &&
          p.length === 2 &&
          p.every((v) => typeof v === "number" && v >= 0 && v <= 1),
      );
  }
  for (const s of doc.entitySources)
    check(
      object(s) &&
        text(s.id) &&
        text(s.label) &&
        text(s.type) &&
        text(s.category) &&
        typeof s.trackAvailable === "boolean",
    );
  for (const c of doc.conditions) {
    check(
      object(c) &&
        text(c.id) &&
        text(c.label) &&
        ["inside", "visible_color", "count"].includes(c.kind) &&
        text(c.source),
    );
    if (c.region !== undefined) check(text(c.region));
    if (c.kind === "visible_color") {
      check(
        text(c.color) &&
          ["whole", "upper", "lower"].includes(c.part ?? "whole") &&
          typeof c.minimumFraction === "number" &&
          text(c.semanticQuery),
      );
      if (c.semanticBinding !== undefined) {
        check(
          object(c.semanticBinding) &&
            ["custom", "generated"].includes(c.semanticBinding.mode) &&
            object(c.semanticBinding.reviewedContext),
        );
        for (const key of ["source", "category", "color", "part"] as const)
          check(text(c.semanticBinding.reviewedContext[key]));
      }
    }
    if (c.kind === "count") check(typeof c.value === "number");
    if (c.time) timeShape(c.time);
    if (c.validity) validityShape(c.validity);
  }
  for (const b of doc.branches) {
    check(
      object(b) &&
        text(b.id) &&
        text(b.name) &&
        text(b.source) &&
        text(b.resultType) &&
        text(b.identity) &&
        object(b.logic) &&
        strings(b.logic.members),
    );
    timeShape(b.time);
    validityShape(b.validity);
  }
  for (const g of doc.groups) {
    check(
      object(g) &&
        text(g.id) &&
        text(g.name) &&
        text(g.operator) &&
        strings(g.members),
    );
    if (g.correlation)
      check(
        object(g.correlation) &&
          text(g.correlation.mode) &&
          text(g.correlation.source),
      );
    if (g.transition)
      check(
        object(g.transition) &&
          text(g.transition.from) &&
          text(g.transition.to) &&
          typeof g.transition.minGapSeconds === "number" &&
          typeof g.transition.maxGapSeconds === "number",
      );
    if (g.validity) validityShape(g.validity);
  }
  check(
    object(doc.final) &&
      text(doc.final.id) &&
      text(doc.final.label) &&
      text(doc.final.type) &&
      ["AND", "OR", "NOT"].includes(doc.final.operator) &&
      strings(doc.final.members),
  );
  for (const o of doc.outputs)
    check(
      object(o) &&
        text(o.id) &&
        text(o.name) &&
        text(o.source) &&
        text(o.resultType) &&
        text(o.delivery) &&
        object(o.trigger) &&
        text(o.trigger.mode),
    );
  check(object(doc.runSettings));
  check(
    validateSettings(readSettings(doc)).length === 0,
    "技能的运行设置无效，未保存或导入。",
  );
  // Unfinished geometry and explicit evidence review are valid draft states.
  const blocked = validateIssues(doc).filter(
    (i) =>
      i.code !== "evidence_review" &&
      !(i.kind === "region" && i.message.includes("尚未绘制并保存")),
  );
  check(!blocked.length, blocked.map((i) => i.message).join(" "));
  const ids = new Set(doc.entitySources.map((s) => s.id));
  for (const c of doc.conditions) ids.add(c.id);
  const visit = (id: string, path: Set<string>) => {
    check(!path.has(id), "目标来源存在循环引用，未导入。");
    const c = doc.conditions.find((item) => item.id === id);
    if (c) visit(c.source, new Set(path).add(id));
  };
  for (const c of doc.conditions) visit(c.id, new Set());
  for (const b of doc.branches)
    check(ids.has(b.source), `${b.name}的来源不存在。`);
  for (const o of doc.outputs)
    check(
      resultSources(doc).some(
        (s) => s.id === o.source && s.types.includes(o.resultType),
      ),
      "输出引用无效。",
    );
}
export function emptyArchive(skillId: string): VersionArchive {
  return { schemaVersion: 1, skillId, versions: [] };
}
export function assertArchive(
  value: unknown,
  skillId: string,
): asserts value is VersionArchive {
  safeJson(value);
  check(
    object(value) &&
      value.schemaVersion === 1 &&
      value.skillId === skillId &&
      Array.isArray(value.versions),
    "保存的版本列表无效，未覆盖旧缓存。",
  );
  const numbers = new Set<number>(),
    ids = new Set<string>();
  for (const r of value.versions) {
    check(
      object(r) &&
        text(r.id) &&
        Number.isInteger(r.number) &&
        Number(r.number) > 0 &&
        text(r.createdAt) &&
        Number.isFinite(Date.parse(r.createdAt)) &&
        text(r.note) &&
        r.note.length <= 200,
      "版本记录格式无效。",
    );
    assertVersionDocument(r.document);
    check(
      r.document.id === skillId &&
        !numbers.has(Number(r.number)) &&
        !ids.has(r.id),
      "版本身份重复或不属于当前技能。",
    );
    numbers.add(Number(r.number));
    ids.add(r.id);
    if (r.importedFrom !== undefined) {
      check(object(r.importedFrom));
      if (r.importedFrom.number !== undefined)
        check(
          Number.isInteger(r.importedFrom.number) &&
            Number(r.importedFrom.number) > 0,
        );
      if (r.importedFrom.createdAt !== undefined)
        check(
          text(r.importedFrom.createdAt) &&
            Number.isFinite(Date.parse(r.importedFrom.createdAt)),
        );
    }
  }
}
export function appendVersion(
  archive: VersionArchive,
  document: SkillDocument,
  note: string,
  now = new Date().toISOString(),
): VersionArchive {
  assertArchive(archive, document.id);
  assertVersionDocument(document);
  check(archive.versions.length < 2000, "保存版本过多，请先导出备份。");
  check(note.trim().length <= 200, "版本说明最多 200 字。");
  const number = Math.max(0, ...archive.versions.map((r) => r.number)) + 1;
  const next: VersionArchive = {
    ...clone(archive),
    versions: [
      ...clone(archive.versions),
      {
        id: crypto.randomUUID(),
        number,
        createdAt: now,
        note: note.trim(),
        document: clone(document),
      },
    ],
  };
  check(
    new TextEncoder().encode(
      JSON.stringify(versionFile(next.versions.at(-1)!), null, 2),
    ).length <= VERSION_FILE_LIMIT,
    "技能配置超过 2 MB，版本未保存。请勿在配置中嵌入媒体或大段数据。",
  );
  return next;
}
export function versionFile(version: SkillVersion) {
  return {
    format: "vsf-skill-version",
    schemaVersion: 1,
    version: clone(version),
  };
}
export function draftFile(document: SkillDocument, note = "") {
  assertVersionDocument(document);
  return {
    format: "vsf-skill-document",
    schemaVersion: 1,
    document: clone(document),
    note,
  };
}
export function parseVersionFile(
  raw: string,
  skillId?: string,
): { document: SkillDocument; note: string; original?: SkillVersion } {
  check(
    new TextEncoder().encode(raw).length <= VERSION_FILE_LIMIT,
    "文件超过 2 MB，未导入。素材文件不应嵌入技能 JSON。",
  );
  let file: unknown;
  try {
    file = JSON.parse(raw.replace(/^\uFEFF/, ""));
  } catch {
    throw new Error("不是有效的 JSON 文件，当前草稿与版本未改变。");
  }
  safeJson(file);
  check(object(file) && file.schemaVersion === 1, "不支持这个文件格式或版本。");
  let document: unknown,
    note = "导入完整技能",
    original: SkillVersion | undefined;
  if (file.format === "vsf-skill-version") {
    check(object(file.version));
    original = file.version as unknown as SkillVersion;
    const identity =
      skillId ?? (object(file.version.document) && file.version.document.id);
    check(text(identity), "技能身份无效。");
    assertArchive(
      { schemaVersion: 1, skillId: identity, versions: [original] },
      identity,
    );
    document = original.document;
    note = original.note;
  } else if (file.format === "vsf-skill-document") {
    document = file.document;
    if (text(file.note)) note = file.note;
  } else if (file.format === "vsf-frontend-demo") document = file.draft;
  else
    throw new Error(
      "不支持这个文件格式。请导入完整技能或此前导出的完整演示配置。",
    );
  assertVersionDocument(document);
  check(
    !skillId || document.id === skillId,
    "文件属于其它技能。请在对应技能的版本页导入；当前技能不会被替换。",
  );
  check(note.length <= 200, "版本说明最多 200 字。");
  return {
    document: clone(document),
    note,
    original: original && clone(original),
  };
}
export function importVersion(
  archive: VersionArchive,
  raw: string,
): { archive: VersionArchive; selected: SkillVersion; duplicate: boolean } {
  const file = parseVersionFile(raw, archive.skillId);
  const existing =
    file.original && archive.versions.find((r) => r.id === file.original?.id);
  if (existing) {
    check(
      JSON.stringify(existing.document) ===
        JSON.stringify(file.original!.document) &&
        existing.note === file.original!.note &&
        (existing.importedFrom?.number ?? existing.number) ===
          (file.original!.importedFrom?.number ?? file.original!.number) &&
        (existing.importedFrom?.createdAt ?? existing.createdAt) ===
          (file.original!.importedFrom?.createdAt ?? file.original!.createdAt),
      "版本身份冲突，未覆盖已保存的版本。",
    );
    return { archive, selected: clone(existing), duplicate: true };
  }
  const next = appendVersion(archive, file.document, file.note);
  const selected = next.versions[next.versions.length - 1];
  if (file.original) {
    selected.id = file.original.id;
    selected.importedFrom = file.original.importedFrom ?? {
      number: file.original.number,
      createdAt: file.original.createdAt,
    };
  }
  return { archive: next, selected, duplicate: false };
}
export function demoArchive(document: SkillDocument): VersionArchive {
  let archive = emptyArchive(document.id);
  for (const [i, note] of [
    "初始演示版本",
    "优化区域标注与规则描述",
    "调整证据画面与输出内容",
  ].entries()) {
    const snapshot = clone(document);
    if (i < 2)
      for (const c of snapshot.conditions)
        if (c.kind === "visible_color")
          c.minimumFraction = i === 0 ? 0.3 : 0.25;
    archive = appendVersion(
      archive,
      snapshot,
      note,
      `2026-10-${[8, 10, 17][i].toString().padStart(2, "0")}T10:26:00+08:00`,
    );
    archive.versions[i].id = `fixture-${document.id}-v${i + 1}`;
  }
  return archive;
}
