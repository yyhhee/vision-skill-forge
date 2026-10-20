export const LIBRARY_KEY = "vsf-frontend-library-v1";
export const CUSTOM_WORKSPACE_PREFIX = "vsf-frontend-skill-v1:";
export const builtInIds = ["regional-alert", "sequence-demo"];
export type LibraryIndex = {
  schemaVersion: 1;
  ids: string[];
  removed: string[];
};
export const validSkillId = (id: string) =>
  /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$/.test(id);
export function workspaceKey(id: string) {
  if (id === "regional-alert") return "vsf-frontend-workspace-v1";
  if (id === "sequence-demo") return "vsf-frontend-sequence-v1";
  return CUSTOM_WORKSPACE_PREFIX + encodeURIComponent(id);
}
export function routeSkillId() {
  const match = location.pathname.match(
    /^\/skills\/([^/]+)\/(?:editor|validate|versions)\/?$/,
  );
  if (match)
    try {
      return decodeURIComponent(match[1]);
    } catch {
      return "invalid";
    }
  // Existing run URLs carry their own immutable skill snapshot.
  if (location.pathname.startsWith("/runs/")) {
    try {
      const runId = decodeURIComponent(location.pathname.split("/")[2]);
      const run = JSON.parse(
        localStorage.getItem("vsf-frontend-run-v1") ?? "{}",
      ).runs?.find((r: { id: string }) => r.id === runId);
      if (typeof run?.snapshot?.id === "string") return run.snapshot.id;
    } catch {
      /* The run experience reports damaged archives. */
    }
  }
  return "regional-alert";
}
export function readLibraryIndex(): LibraryIndex {
  const raw = localStorage.getItem(LIBRARY_KEY);
  if (!raw) return { schemaVersion: 1, ids: [], removed: [] };
  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error(
      "技能目录缓存已损坏，原内容未覆盖。请先导出仍可读取的配置备份。",
    );
  }
  if (
    value?.schemaVersion !== 1 ||
    !Array.isArray(value.ids) ||
    !Array.isArray(value.removed) ||
    ![...value.ids, ...value.removed].every(
      (id) => typeof id === "string" && validSkillId(id),
    ) ||
    new Set(value.ids).size !== value.ids.length ||
    new Set(value.removed).size !== value.removed.length
  )
    throw new Error(
      "技能目录缓存已损坏，原内容未覆盖。请先导出仍可读取的配置备份。",
    );
  return value;
}
export function skillRemoved(id: string) {
  return readLibraryIndex().removed.includes(id);
}
