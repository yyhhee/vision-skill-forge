import {
  clone,
  seedWorkspace,
  type SkillDocument,
  type WorkspaceData,
} from "./document";
import { createSequenceDocument } from "./editor";
import {
  draftFile,
  emptyArchive,
  importVersion,
  parseVersionFile,
  versionStorageKey,
} from "./versions";
import {
  builtInIds,
  LIBRARY_KEY,
  readLibraryIndex,
  validSkillId,
  workspaceKey,
} from "./skillStorage";
import { RUN_STORAGE_KEY, validStoredRun, type DemoRun } from "./runs";
import { validateIssues } from "./validation";

export function initialSkill(id: string): WorkspaceData {
  if (!builtInIds.includes(id)) throw new Error("没有提供这个模板的完整配置。");
  const seed = seedWorkspace();
  if (id === "sequence-demo") {
    seed.draft = createSequenceDocument(seed.draft);
    seed.applied = clone(seed.draft);
    seed.revision = 0;
  }
  return seed;
}
export function readSkill(id: string): WorkspaceData {
  if (!validSkillId(id)) throw new Error("技能地址无效。");
  const index = readLibraryIndex();
  if (index.removed.includes(id))
    throw new Error("这个本地技能已删除，历史运行记录仍保留。");
  const raw = localStorage.getItem(workspaceKey(id));
  if (!raw) {
    if (builtInIds.includes(id)) return initialSkill(id);
    throw new Error("未找到这个本地技能，请返回技能库导入或新建。");
  }
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error("技能缓存不可读取，原内容未覆盖。");
  }
  if (
    !data?.draft ||
    !data?.applied ||
    !Number.isInteger(data.revision) ||
    data.revision < 0 ||
    data.draft.id !== id ||
    data.applied.id !== id
  )
    throw new Error("技能缓存不可读取，原内容未覆盖。");
  // Drafts can deliberately contain validation issues; preserve them for editing.
  for (const doc of [data.draft, data.applied])
    if (
      typeof doc.name !== "string" ||
      typeof doc.instruction !== "string" ||
      !doc.final ||
      ![
        "conditions",
        "branches",
        "groups",
        "regions",
        "outputs",
        "entitySources",
      ].every((key) => Array.isArray(doc[key]))
    )
      throw new Error("技能结构不完整，原内容未覆盖。");
  if (data.revision > 0 && validateIssues(data.applied).length)
    throw new Error("当前运行快照结构无效，原内容未覆盖。");
  return data;
}
export type LocalSkill = { id: string; data?: WorkspaceData; error?: string };
export function listLocalSkills(): LocalSkill[] {
  const index = readLibraryIndex();
  return [...new Set([...builtInIds, ...index.ids])]
    .filter((id) => !index.removed.includes(id))
    .map((id) => {
      try {
        return { id, data: readSkill(id) };
      } catch (e) {
        return { id, error: (e as Error).message };
      }
    });
}
function transaction(changes: [string, string | null][]) {
  const previous = changes.map(
    ([key]) => [key, localStorage.getItem(key)] as const,
  );
  try {
    for (const [key, value] of changes)
      value === null
        ? localStorage.removeItem(key)
        : localStorage.setItem(key, value);
  } catch {
    // Roll back only keys touched by this operation, never clear browser storage.
    for (const [key, value] of previous.reverse()) {
      try {
        value === null
          ? localStorage.removeItem(key)
          : localStorage.setItem(key, value);
      } catch {
        /* Preserve the original failure below. */
      }
    }
    throw new Error(
      "未保存：本地存储不可用或空间不足，未确认成功。请导出文件备份后重试。",
    );
  }
  window.dispatchEvent(new Event("vsf:library-changed"));
}
function newIdentity() {
  return "skill-" + crypto.randomUUID();
}
export function installSkill(raw: string, asCopy = false) {
  const file = parseVersionFile(raw);
  if (!validSkillId(file.document.id))
    throw new Error("技能身份须为字母、数字、点、横线或下划线，长度不超过96。");
  const index = readLibraryIndex();
  const exists =
    !index.removed.includes(file.document.id) &&
    (builtInIds.includes(file.document.id) ||
      index.ids.includes(file.document.id) ||
      localStorage.getItem(workspaceKey(file.document.id)) !== null);
  if ((exists || index.removed.includes(file.document.id)) && !asCopy)
    return {
      conflict: true as const,
      document: file.document,
      reason: index.removed.includes(file.document.id) ? "deleted" : "exists",
    };
  const document = clone(file.document);
  if (asCopy) {
    document.id = newIdentity();
    document.name = document.name.slice(0, 110) + "（导入副本）";
  }
  // A deleted identity must not silently become a different skill under old run IDs.
  if (index.removed.includes(document.id))
    throw new Error(
      "此技能身份已经删除。请另存为新技能副本，避免与历史记录混淆。",
    );
  const imported = asCopy
    ? importVersion(
        emptyArchive(document.id),
        JSON.stringify(draftFile(document, file.note)),
      )
    : importVersion(emptyArchive(document.id), raw);
  const workspace: WorkspaceData = {
    draft: document,
    applied: clone(document),
    revision: 0,
  };
  transaction([
    [versionStorageKey(document.id), JSON.stringify(imported.archive)],
    [workspaceKey(document.id), JSON.stringify(workspace)],
    [
      LIBRARY_KEY,
      JSON.stringify({
        ...index,
        ids: [...new Set([...index.ids, document.id])],
      }),
    ],
  ]);
  return { conflict: false as const, document };
}
export function createFromTemplate(template: string, name: string) {
  if (!builtInIds.includes(template))
    throw new Error("请选择已提供完整配置的模板。");
  if (!name.trim() || name.trim().length > 120)
    throw new Error("技能名称为1–120字。");
  const document: SkillDocument = {
    ...initialSkill(template).draft,
    id: newIdentity(),
    name: name.trim(),
  };
  return installSkill(
    JSON.stringify(draftFile(document, "从明确的演示模板新建；未调用LLM")),
  );
}
export function skillRuns(id: string): DemoRun[] {
  const raw = localStorage.getItem(RUN_STORAGE_KEY);
  if (!raw) return [];
  const archive = JSON.parse(raw);
  if (
    archive?.schemaVersion !== 1 ||
    !Array.isArray(archive.runs) ||
    !archive.runs.every(validStoredRun)
  )
    throw new Error("运行记录缓存不可读取，无法安全检查引用；未删除技能。");
  return archive.runs.filter((run: DemoRun) => run.snapshot.id === id);
}
export function deleteLocalSkill(id: string) {
  const data = readSkill(id);
  if (skillRuns(id).some((run) => run.status === "running"))
    throw new Error("该技能仍有未结束任务，请先停止任务。历史结果不会被删除。");
  const index = readLibraryIndex();
  transaction([
    [
      LIBRARY_KEY,
      JSON.stringify({
        ...index,
        ids: index.ids.filter((item) => item !== id),
        removed: [...new Set([...index.removed, id])],
      }),
    ],
    [workspaceKey(id), null],
    [versionStorageKey(id), null],
  ]);
}
