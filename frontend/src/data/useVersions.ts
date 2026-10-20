import { useEffect, useState } from "react";
import type { SkillDocument } from "./document";
import {
  appendVersion,
  assertArchive,
  demoArchive,
  emptyArchive,
  importVersion,
  versionStorageKey,
  type VersionArchive,
} from "./versions";

export function useVersions(
  document: SkillDocument,
  applied: SkillDocument,
  fixture: string,
) {
  const isolated = !!fixture;
  const key = versionStorageKey(document.id);
  const read = (): { archive: VersionArchive; warning: string } => {
    try {
      if (isolated)
        return {
          archive:
            fixture === "12" ? demoArchive(applied) : emptyArchive(document.id),
          warning: "",
        };
      const raw = localStorage.getItem(key);
      if (!raw) return { archive: emptyArchive(document.id), warning: "" };
      const archive: unknown = JSON.parse(raw);
      assertArchive(archive, document.id);
      return { archive, warning: "" };
    } catch {
      return {
        archive: emptyArchive(document.id),
        warning: "版本缓存不可用或已损坏，旧内容未覆盖。可先导出当前草稿备份。",
      };
    }
  };
  const [state, setState] = useState(read);
  useEffect(() => {
    if (isolated) return;
    const sync = (event: StorageEvent) => {
      if (event.key === key || event.key === null) setState(read());
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, [key, isolated]);
  const current = () => {
    if (isolated) return state.archive;
    const fresh = read();
    if (fresh.warning) throw new Error(fresh.warning);
    return fresh.archive;
  };
  const persist = (archive: VersionArchive) => {
    try {
      if (!isolated) localStorage.setItem(key, JSON.stringify(archive));
    } catch {
      throw new Error(
        "版本未保存：本地存储不可用或空间不足。当前草稿未改变，可导出文件备份。",
      );
    }
    setState({ archive, warning: "" });
  };
  const save = (doc: SkillDocument, note: string) => {
    const next = appendVersion(current(), doc, note);
    persist(next);
    return next.versions[next.versions.length - 1];
  };
  const importFile = (raw: string) => {
    const result = importVersion(current(), raw);
    if (!result.duplicate) persist(result.archive);
    else setState({ archive: result.archive, warning: "" });
    return result;
  };
  return { archive: state.archive, warning: state.warning, save, importFile };
}
