import type { WorkspaceData } from "./document";
import { initialSkill, listLocalSkills } from "./skillRepository";

export type LibraryEntry = {
  id: string;
  name: string;
  instruction: string;
  thumbnail?: string;
  origin: "local" | "reference";
  data?: WorkspaceData;
  error?: string;
};
export const referenceEntries: LibraryEntry[] = [
  {
    id: "furniture",
    name: "黄色沙发与白色椅子",
    instruction: "检测画面中是否同时出现黄色沙发和白色椅子。",
    thumbnail: "furniture",
    origin: "reference",
  },
  {
    id: "lane-traffic",
    name: "多车道拥堵",
    instruction: "检测道路画面中的车道拥堵情况。",
    thumbnail: "traffic",
    origin: "reference",
  },
  {
    id: "road-debris",
    name: "道路抛洒物",
    instruction: "检测道路上的抛洒物，支持图片或视频。",
    thumbnail: "debris",
    origin: "reference",
  },
  {
    id: "bridge-damage",
    name: "桥梁病害",
    instruction: "识别桥梁结构表面的常见病害问题。",
    thumbnail: "bridge",
    origin: "reference",
  },
];
export function libraryEntries(fixture = ""): LibraryEntry[] {
  const local = fixture
    ? [{ id: "regional-alert", data: initialSkill("regional-alert") }]
    : listLocalSkills();
  return [
    ...local.map((item) => ({
      id: item.id,
      name: item.data?.draft.name ?? item.id,
      instruction:
        item.data?.draft.instruction ?? "缓存不可读取，未覆盖原数据。",
      data: item.data,
      error: item.error,
      origin: "local" as const,
    })),
    ...referenceEntries.filter(
      (entry) => !local.some((item) => item.id === entry.id),
    ),
  ];
}
export function entryThumbnail(entry: LibraryEntry) {
  if (entry.thumbnail) return `/assets/library/${entry.thumbnail}.png`;
  return entry.data?.draft.mediaRef === "construction-poster"
    ? "/assets/media/construction-clean.png"
    : undefined;
}
export const workspaceDirty = (data: WorkspaceData) =>
  data.revision === 0 ||
  JSON.stringify(data.draft) !== JSON.stringify(data.applied);
export function entryStatus(entry: LibraryEntry) {
  if (entry.error) return "缓存待检查";
  if (!entry.data) return "示例说明";
  if (!entry.data.revision) return "草稿 · 尚未应用";
  return workspaceDirty(entry.data) ? "草稿有修改" : "已应用";
}
