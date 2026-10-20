import fixtures from "../fixtures/mock-fixtures.json";
import {
  RUN_STORAGE_KEY,
  exampleRun,
  poster,
  validStoredRun,
  type DemoRun,
} from "./runs";
import { referenceEntries } from "./libraryEntries";
export type HistoryRow = {
  id: string;
  skillId: string;
  name: string;
  status: DemoRun["status"];
  revision: number | null;
  createdAt: string;
  media: "image" | "video_demo" | "unknown";
  mediaLabel: string;
  thumbnail?: string;
  eventCount: number | null;
  evidenceCount: number | null;
  run?: DemoRun;
};
export const historyStatusNames: Record<DemoRun["status"], string> = {
  running: "未结束",
  completed: "已完成",
  cancelled: "已停止",
  failed: "失败",
};
export function readRunArchive(): { runs: DemoRun[]; raw: string | null } {
  const raw = localStorage.getItem(RUN_STORAGE_KEY);
  if (raw === null) return { runs: [], raw };
  try {
    const value = JSON.parse(raw);
    if (
      value?.schemaVersion !== 1 ||
      !Array.isArray(value.runs) ||
      !value.runs.every(
        (r: unknown) =>
          validStoredRun(r) && r.id.trim().length > 0 && r.id.length <= 200,
      ) ||
      new Set(value.runs.map((r: DemoRun) => r.id)).size !== value.runs.length
    )
      throw new Error("invalid archive");
    return { runs: value.runs, raw };
  } catch {
    throw new Error(
      "运行记录缓存不可读取或不兼容，原内容未覆盖。请备份原始缓存后检查，不会用演示记录替代。",
    );
  }
}
export function rowFromRun(run: DemoRun): HistoryRow {
  const known = run.snapshot.mediaRef === "construction-poster";
  const hasResult =
    run.status === "completed" && run.resultAvailability === "scripted";
  return {
    id: run.id,
    skillId: run.snapshot.id,
    name: run.snapshot.name,
    status: run.status,
    revision: run.revision,
    createdAt: run.createdAt,
    media: known ? (run.snapshot.mediaMode ?? "video_demo") : "unknown",
    mediaLabel: known
      ? run.snapshot.mediaMode === "image"
        ? "施工海报 · 图片模拟"
        : "施工海报 · 视频模拟"
      : "素材未接入",
    thumbnail: known ? poster : undefined,
    eventCount: hasResult ? run.events.length : null,
    evidenceCount: hasResult
      ? run.events.reduce((n, e) => n + e.evidence.length, 0)
      : null,
    run,
  };
}
export function fixtureHistory(): HistoryRow[] {
  return fixtures.history.map((item) => {
    if (item.id === "run-regional-r3") return rowFromRun(exampleRun(true));
    const reference = referenceEntries.find((e) => e.id === item.skillId);
    return {
      id: item.id,
      skillId: item.skillId,
      name: item.name,
      status: item.status as DemoRun["status"],
      revision: null,
      createdAt: item.at,
      media: ["bridge-damage", "furniture"].includes(item.skillId)
        ? "image"
        : "video_demo",
      mediaLabel: ["bridge-damage", "furniture"].includes(item.skillId)
        ? "参考海报 · 图片示例"
        : "参考海报 · 视频示例",
      thumbnail: reference?.thumbnail
        ? `/assets/library/${reference.thumbnail}.png`
        : undefined,
      eventCount: item.eventCount,
      evidenceCount: null,
    };
  });
}
export type DateRange = {
  mode: "all" | "today" | "week" | "custom";
  from: string;
  to: string;
};
export type HistoryFilter = {
  search: string;
  status: "all" | DemoRun["status"];
  media: "all" | HistoryRow["media"];
  skillId: string;
  range: DateRange;
};
export const emptyHistoryFilter = (): HistoryFilter => ({
  search: "",
  status: "all",
  media: "all",
  skillId: "",
  range: { mode: "all", from: "", to: "" },
});
export function historyRoute(search: string) {
  const p = new URLSearchParams(search),
    filter = emptyHistoryFilter();
  filter.search = (p.get("q") ?? "").slice(0, 500);
  filter.skillId = (p.get("skill") ?? "").slice(0, 200);
  if (
    ["running", "completed", "cancelled", "failed"].includes(
      p.get("status") ?? "",
    )
  )
    filter.status = p.get("status") as HistoryFilter["status"];
  if (["image", "video_demo", "unknown"].includes(p.get("media") ?? ""))
    filter.media = p.get("media") as HistoryFilter["media"];
  if (["today", "week", "custom"].includes(p.get("range") ?? ""))
    filter.range = {
      mode: p.get("range") as DateRange["mode"],
      from: p.get("from") ?? "",
      to: p.get("to") ?? "",
    };
  const requestedPage = Number(p.get("page") ?? 1);
  return {
    filter,
    page:
      Number.isInteger(requestedPage) &&
      requestedPage > 0 &&
      requestedPage <= 1000000
        ? requestedPage
        : 1,
    selected: p.get("selected"),
  };
}
export function historyDate(value: string | number) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const get = (key: string) => parts.find((p) => p.type === key)!.value;
  return {
    day: `${get("year")}-${get("month")}-${get("day")}`,
    time: `${get("hour")}:${get("minute")}`,
  };
}
const validDay = (s: string) =>
  /^\d{4}-\d{2}-\d{2}$/.test(s) &&
  Number.isFinite(Date.parse(s)) &&
  new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;
export function dateRangeError(range: DateRange) {
  if (!["all", "today", "week", "custom"].includes(range.mode))
    return "日期范围无效。";
  if (
    range.mode === "custom" &&
    (!validDay(range.from) || !validDay(range.to) || range.from > range.to)
  )
    return "请选择有效的开始与结束日期，结束不得早于开始。";
  return "";
}
export function filterHistory(
  rows: HistoryRow[],
  filter: HistoryFilter,
  now = Date.now(),
): HistoryRow[] {
  if (dateRangeError(filter.range)) return [];
  const today = historyDate(now).day,
    weekStart = historyDate(now - 6 * 86400000).day;
  return rows
    .filter((r) => {
      const day = historyDate(r.createdAt).day;
      const inRange =
        filter.range.mode === "all" ||
        (filter.range.mode === "today" && day === today) ||
        (filter.range.mode === "week" && day >= weekStart && day <= today) ||
        (filter.range.mode === "custom" &&
          day >= filter.range.from &&
          day <= filter.range.to);
      return (
        inRange &&
        (filter.status === "all" || r.status === filter.status) &&
        (filter.media === "all" || r.media === filter.media) &&
        (!filter.skillId || r.skillId === filter.skillId) &&
        `${r.name} ${r.mediaLabel} ${r.id} ${r.revision ? `R${r.revision}` : ""}`
          .toLowerCase()
          .includes(filter.search.trim().toLowerCase())
      );
    })
    .sort(
      (a, b) =>
        Date.parse(b.createdAt) - Date.parse(a.createdAt) ||
        a.id.localeCompare(b.id),
    );
}
export function historyExport(row: HistoryRow) {
  if (row.run) return structuredClone(row.run);
  const { run, ...summary } = row;
  return {
    format: "vsf-run-summary",
    schemaVersion: 1,
    demo: true,
    snapshotIncluded: false,
    detailsAvailable: false,
    summary,
  };
}
