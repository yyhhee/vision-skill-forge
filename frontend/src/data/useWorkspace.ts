import { useCallback, useEffect, useState } from "react";
import {
  applyDraft,
  clone,
  seedWorkspace,
  validateDocument,
  type SkillDocument,
  type WorkspaceData,
} from "./document";
import { createSequenceDocument } from "./editor";
import {
  builtInIds,
  routeSkillId,
  skillRemoved,
  workspaceKey,
} from "./skillStorage";
import { RUN_STORAGE_KEY, validStoredRun, type DemoRun } from "./runs";

const fixture = new URLSearchParams(location.search).get("fixture") ?? "";
const screenshotMode = !!fixture;
function seed(skillId: string) {
  const data = seedWorkspace(fixture);
  if (fixture === "09") data.draft = clone(data.applied);
  if (skillId === "sequence-demo") {
    data.draft = createSequenceDocument(data.draft);
    data.applied = clone(data.draft);
    data.revision = 0;
  }
  return data;
}
function structure(doc: SkillDocument) {
  return (
    typeof doc?.instruction === "string" &&
    Array.isArray(doc.regions) &&
    Array.isArray(doc.conditions) &&
    Array.isArray(doc.branches) &&
    Array.isArray(doc.groups) &&
    Array.isArray(doc.entitySources) &&
    Array.isArray(doc.outputs) &&
    Array.isArray(doc.final?.members)
  );
}
function load(skillId: string): {
  data: WorkspaceData;
  storageWarning: boolean;
  historyOnly?: boolean;
} {
  if (screenshotMode) return { data: seed(skillId), storageWarning: false };
  try {
    const text = localStorage.getItem(workspaceKey(skillId));
    if (
      location.pathname.startsWith("/runs/") &&
      (!text || skillRemoved(skillId))
    ) {
      const id = decodeURIComponent(location.pathname.split("/")[2]);
      const run = JSON.parse(
        localStorage.getItem(RUN_STORAGE_KEY) ?? "{}",
      ).runs?.find((r: DemoRun) => r.id === id);
      if (run && validStoredRun(run))
        return {
          data: {
            draft: clone(run.snapshot),
            applied: clone(run.snapshot),
            revision: run.revision,
          },
          storageWarning: false,
          historyOnly: true,
        };
    }
    if (!text) return { data: seed(skillId), storageWarning: false };
    const saved = JSON.parse(text) as WorkspaceData;
    if (
      !saved.draft ||
      !saved.applied ||
      !Number.isInteger(saved.revision) ||
      !structure(saved.draft) ||
      !structure(saved.applied) ||
      (saved.revision > 0 && validateDocument(saved.applied).length)
    )
      throw new Error("Invalid storage");
    return { data: saved, storageWarning: false };
  } catch {
    return { data: seed(skillId), storageWarning: true };
  }
}
export function useWorkspace() {
  const [skillId] = useState(routeSkillId);
  const [initial] = useState(() => load(skillId));
  const [data, setData] = useState(initial.data);
  const [past, setPast] = useState<SkillDocument[]>([]);
  const [future, setFuture] = useState<SkillDocument[]>([]);
  const [storageWarning, setStorageWarning] = useState(initial.storageWarning);
  const [persistenceBlocked, setPersistenceBlocked] = useState(
    initial.storageWarning || !!initial.historyOnly,
  );
  useEffect(() => {
    if (screenshotMode || persistenceBlocked) return;
    try {
      if (skillRemoved(skillId) || data.draft.id !== skillId)
        throw new Error("This skill was deleted or is incompatible");
      localStorage.setItem(workspaceKey(skillId), JSON.stringify(data));
    } catch {
      setStorageWarning(true);
    }
  }, [data, persistenceBlocked]);
  // Synchronous before navigating out: React may unmount before passive effects.
  const flush = (document?: SkillDocument) => {
    if (screenshotMode) return true;
    if (persistenceBlocked) return false;
    try {
      if (skillRemoved(skillId) || (document ?? data.draft).id !== skillId)
        throw new Error("This skill was deleted or is incompatible");
      localStorage.setItem(
        workspaceKey(skillId),
        JSON.stringify(document ? { ...data, draft: clone(document) } : data),
      );
      return true;
    } catch {
      setStorageWarning(true);
      return false;
    }
  };
  const commit = useCallback(
    (document: SkillDocument) => {
      setPast((p) => [...p.slice(-29), clone(data.draft)]);
      setFuture([]);
      setData((d) => ({ ...d, draft: clone(document) }));
    },
    [data.draft],
  );
  const undo = useCallback(() => {
    if (!past.length) return;
    setFuture((f) => [clone(data.draft), ...f]);
    setData((d) => ({ ...d, draft: clone(past[past.length - 1]) }));
    setPast((p) => p.slice(0, -1));
  }, [past, data.draft]);
  const redo = useCallback(() => {
    if (!future.length) return;
    setPast((p) => [...p, clone(data.draft)]);
    setData((d) => ({ ...d, draft: clone(future[0]) }));
    setFuture((f) => f.slice(1));
  }, [future, data.draft]);
  const apply = useCallback(
    (document?: SkillDocument) =>
      setData((d) =>
        applyDraft(document ? { ...d, draft: clone(document) } : d),
      ),
    [],
  );
  const reset = useCallback(() => {
    setData(builtInIds.includes(skillId) ? seed(skillId) : clone(initial.data));
    setPast([]);
    setFuture([]);
    setPersistenceBlocked(false);
    setStorageWarning(false);
  }, []);
  const dirty =
    data.revision === 0 ||
    JSON.stringify(data.draft) !== JSON.stringify(data.applied);
  return {
    data,
    commit,
    undo,
    redo,
    apply,
    reset,
    dirty,
    canUndo: !!past.length,
    canRedo: !!future.length,
    storageWarning,
    screenshotMode,
    flush,
    historyOnly: !!initial.historyOnly,
  };
}
