import type { SkillDocument } from "./document";
import { readSettings } from "./runs";
import {
  capabilityClosure,
  catalog,
  enabled,
  readCapabilities,
  seedCapabilities,
  type CapabilityRegistry,
} from "./capabilities";

/** Runtime availability is deliberately separate from document/schema validity. */
export function requiredCapabilities(doc: SkillDocument): string[] {
  const ids = new Set<string>(doc.capabilityRefs ?? []);
  if (doc.entitySources.length) ids.add("detect");
  if (readSettings(doc).dedup) ids.add("instance-dedup");
  for (const c of doc.conditions) {
    if (c.kind === "inside") ids.add("region-membership");
    else if (c.kind === "count") ids.add("count");
    else if (c.kind === "visible_color") {
      if (c.evidenceMode === "fraction_only") ids.add("color-fraction");
      else if (c.evidenceMode === "semantic_only") ids.add("same-subject");
      else ids.add("color-review");
    } else ids.add(`unsupported:${c.kind}`);
    if (c.sameEntityRequired && c.evidenceMode !== "fraction_only")
      ids.add("same-subject");
  }
  if (doc.groups.some((g) => g.operator === "SEQUENCE"))
    ids.add("temporal-composition");
  if (
    [...doc.conditions, ...doc.branches].some(
      (c) =>
        (c.time && c.time.mode !== "immediate") ||
        (c.validity && c.validity.mode !== "current_frame"),
    ) ||
    doc.groups.some((g) => g.validity && g.validity.mode !== "current_frame") ||
    doc.outputs.some((o) => (o.trigger.cooldownSeconds ?? 0) > 0)
  )
    ids.add("time-window");
  return [...ids];
}
export function unavailableCapabilities(
  doc: SkillDocument,
  registry: CapabilityRegistry,
): string[] {
  const all = catalog(registry);
  return capabilityClosure(registry, requiredCapabilities(doc)).flatMap(
    (id) => {
      const c = all.find((c) => c.id === id);
      if (!c) return [`所需能力「${id}」未安装或未支持。`];
      if (!enabled(registry, id))
        return [`所需能力「${c.name}」已停用，请到能力管理启用。`];
      if (!c.builtin)
        return [
          `自定义能力「${c.name}」仅安装清单，编译器／执行器未接入，不能应用或运行。`,
        ];
      return [];
    },
  );
}
export function capabilityErrors(doc: SkillDocument, fixture = ""): string[] {
  try {
    return unavailableCapabilities(
      doc,
      fixture ? seedCapabilities() : readCapabilities().registry,
    );
  } catch (e) {
    return [(e as Error).message];
  }
}
