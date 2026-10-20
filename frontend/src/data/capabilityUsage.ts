import { capabilityClosure, type CapabilityRegistry } from "./capabilities";
import { requiredCapabilities } from "./capabilityRequirements";
import { listLocalSkills, initialSkill } from "./skillRepository";
import { assertArchive, versionStorageKey } from "./versions";
import { RUN_STORAGE_KEY, validStoredRun, type DemoRun } from "./runs";
export type CapabilityUse = { id: string; name: string; contexts: string[] };
export function capabilityUsage(
  id: string,
  registry: CapabilityRegistry,
  fixture = "",
): CapabilityUse[] {
  const uses = new Map<string, CapabilityUse>();
  const add = (doc: import("./document").SkillDocument, context: string) => {
    if (!capabilityClosure(registry, requiredCapabilities(doc)).includes(id))
      return;
    const row = uses.get(doc.id) ?? {
      id: doc.id,
      name: doc.name,
      contexts: [],
    };
    if (!row.contexts.includes(context)) row.contexts.push(context);
    uses.set(doc.id, row);
  };
  const skills = fixture
    ? ["regional-alert", "sequence-demo"].map((id) => ({
        id,
        data: initialSkill(id),
        error: undefined,
      }))
    : listLocalSkills();
  for (const item of skills) {
    if (!item.data)
      throw new Error(`无法检查技能 ${item.id} 的引用：${item.error}`);
    add(item.data.draft, "草稿");
    if (item.data.revision > 0)
      add(item.data.applied, `运行 R${item.data.revision}`);
    const raw = fixture
      ? null
      : localStorage.getItem(versionStorageKey(item.id));
    if (raw !== null) {
      const archive: unknown = JSON.parse(raw);
      assertArchive(archive, item.id);
      archive.versions.forEach((v) => add(v.document, `保存 V${v.number}`));
    }
  }
  const raw = fixture ? null : localStorage.getItem(RUN_STORAGE_KEY);
  if (raw !== null) {
    const archive = JSON.parse(raw);
    if (
      archive?.schemaVersion !== 1 ||
      !Array.isArray(archive.runs) ||
      !archive.runs.every(validStoredRun)
    )
      throw new Error("运行缓存不可读取，无法安全检查能力引用。");
    archive.runs
      .filter((r: DemoRun) => r.status === "running")
      .forEach((r: DemoRun) => add(r.snapshot, "未结束任务"));
  }
  return [...uses.values()];
}
