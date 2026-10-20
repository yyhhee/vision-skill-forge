import {
  clone,
  seedWorkspace,
  validateDocument,
  type SkillDocument,
} from "./document";

export type RunSettings = {
  sampleIntervalSeconds: number;
  startSeconds: number;
  endSeconds: number;
  maxFrames: number;
  resizeLongEdge: number;
  tiles: {
    enabled: boolean;
    includeFullFrame: boolean;
    width: number;
    height: number;
    overlapX: number;
    overlapY: number;
  };
  dedup: {
    metric: "instance" | "ios" | "iou";
    threshold: number;
    keep: "best_localization";
  };
};
export type DemoEvidence = {
  id: string;
  entityId: string;
  conditionId: string;
  label: string;
  semanticQuery: string;
  fraction: number;
  crop: [number, number, number, number];
};
export type DemoEvent = {
  id: string;
  name: string;
  atSeconds: number;
  entityId: string;
  evidence: DemoEvidence[];
};
export type DemoRun = {
  schemaVersion: 1;
  id: string;
  revision: number;
  snapshot: SkillDocument;
  settings: RunSettings;
  status: "running" | "cancelled" | "failed" | "completed";
  completedFrames: number;
  sampleTimes: number[];
  createdAt: string;
  resultAvailability: "scripted" | "not_provided";
  events: DemoEvent[];
  error?: string;
  demo: true;
};
export const RUN_STORAGE_KEY = "vsf-frontend-run-v1";
export const poster = "/assets/media/construction-clean.png";
export function readSettings(document: SkillDocument): RunSettings {
  const value = (document.runSettings ?? {}) as Partial<RunSettings>;
  return {
    sampleIntervalSeconds: value.sampleIntervalSeconds ?? 1,
    startSeconds: value.startSeconds ?? 0,
    endSeconds: value.endSeconds ?? 30,
    maxFrames: value.maxFrames ?? 0,
    resizeLongEdge: value.resizeLongEdge ?? 1280,
    tiles: {
      enabled: true,
      includeFullFrame: true,
      width: 640,
      height: 640,
      overlapX: 0.2,
      overlapY: 0.2,
      ...value.tiles,
    },
    dedup: {
      metric: "instance",
      threshold: 0.45,
      keep: "best_localization",
      ...value.dedup,
    },
  };
}
export function validateSettings(s: RunSettings): string[] {
  const issues: string[] = [];
  if (
    !Number.isFinite(s.sampleIntervalSeconds) ||
    s.sampleIntervalSeconds < 0.1 ||
    s.sampleIntervalSeconds > 30
  )
    issues.push("采样间隔须为0.1–30秒。");
  if (
    ![s.startSeconds, s.endSeconds].every(Number.isFinite) ||
    s.startSeconds < 0 ||
    s.endSeconds > 30 ||
    s.endSeconds <= s.startSeconds
  )
    issues.push("模拟范围须在0–30秒内，结束大于开始；不包含结束点。");
  if (!Number.isInteger(s.maxFrames) || s.maxFrames < 0 || s.maxFrames > 300)
    issues.push("最大采样帧数须为0–300的整数，0表示不限。");
  if (
    !Number.isInteger(s.resizeLongEdge) ||
    s.resizeLongEdge < 320 ||
    s.resizeLongEdge > 4096
  )
    issues.push("缩放长边须为320–4096像素的整数。");
  if (s.tiles.enabled) {
    if (
      ![s.tiles.width, s.tiles.height].every(
        (v) => Number.isInteger(v) && v >= 128 && v <= 4096,
      )
    )
      issues.push("切片宽高须为128–4096像素的整数。");
    if (
      ![s.tiles.overlapX, s.tiles.overlapY].every(
        (v) => Number.isFinite(v) && v >= 0 && v <= 0.9,
      )
    )
      issues.push("切片覆盖比例须为0–90%。");
  }
  if (
    !["instance", "ios", "iou"].includes(s.dedup.metric) ||
    s.dedup.keep !== "best_localization" ||
    !Number.isFinite(s.dedup.threshold) ||
    s.dedup.threshold < 0 ||
    s.dedup.threshold > 1
  )
    issues.push("请选择有效去重方式，阈值须在0–1之间。");
  return issues;
}
export function sampleTimes(s: RunSettings): number[] {
  if (validateSettings(s).length) return [];
  const count = Math.min(
    300,
    Math.ceil((s.endSeconds - s.startSeconds) / s.sampleIntervalSeconds),
    s.maxFrames || 300,
  );
  return Array.from(
    { length: count },
    (_, i) =>
      Math.round((s.startSeconds + i * s.sampleIntervalSeconds) * 10000) /
      10000,
  ).filter((t) => t < s.endSeconds);
}
function comparable(doc: SkillDocument) {
  const next = clone(doc);
  next.runSettings = null;
  return JSON.stringify(next);
}
export function scriptAvailable(
  doc: SkillDocument,
  settings: RunSettings,
): boolean {
  return (
    comparable(doc) === comparable(seedWorkspace().applied) &&
    sampleTimes(settings).includes(12)
  );
}
export function createRun(
  snapshot: SkillDocument,
  revision: number,
  id = `demo-${crypto.randomUUID()}`,
): DemoRun {
  const settings = readSettings(snapshot);
  if (revision < 1 || validateSettings(settings).length)
    throw new Error("请先生成有效的已应用版本和运行设置。");
  return {
    schemaVersion: 1,
    id,
    revision,
    snapshot: clone(snapshot),
    settings: clone(settings),
    status: "running",
    completedFrames: 0,
    sampleTimes: sampleTimes(settings),
    createdAt: new Date().toISOString(),
    resultAvailability: scriptAvailable(snapshot, settings)
      ? "scripted"
      : "not_provided",
    events: [],
    demo: true,
  };
}
function scriptedEvents(run: DemoRun): DemoEvent[] {
  if (run.resultAvailability !== "scripted") return [];
  const doc = run.snapshot;
  return [
    {
      id: "event-1",
      name: doc.outputs[0].name,
      atSeconds: 12,
      entityId: "person-1",
      evidence: [
        {
          id: "evidence-upper",
          entityId: "person-1",
          conditionId: "a-red",
          label: "红色上衣",
          semanticQuery: doc.conditions.find((c) => c.id === "a-red")!
            .semanticQuery!,
          fraction: 0.35,
          crop: [0.17, 0.495, 0.09, 0.1],
        },
        {
          id: "evidence-lower",
          entityId: "person-1",
          conditionId: "a-gray",
          label: "灰色裤子",
          semanticQuery: doc.conditions.find((c) => c.id === "a-gray")!
            .semanticQuery!,
          fraction: 0.42,
          crop: [0.185, 0.605, 0.065, 0.1],
        },
      ],
    },
  ];
}
export function advanceRun(run: DemoRun): DemoRun {
  if (run.status !== "running") return run;
  const completedFrames = Math.min(
    run.completedFrames + 1,
    run.sampleTimes.length,
  );
  const done = completedFrames === run.sampleTimes.length;
  return {
    ...run,
    completedFrames,
    status: done ? "completed" : "running",
    events: done ? scriptedEvents(run) : [],
  };
}
export function cancelRun(run: DemoRun): DemoRun {
  return run.status === "running"
    ? { ...run, status: "cancelled", events: [] }
    : run;
}
export function failRun(run: DemoRun): DemoRun {
  return run.status === "running"
    ? {
        ...run,
        status: "failed",
        events: [],
        error: "用户触发的模拟失败；未调用模型，未产生业务结果。",
      }
    : run;
}
export function exampleRun(completed = false): DemoRun {
  let run = createRun(seedWorkspace().applied, 3, "run-regional-r3");
  run.createdAt = "2026-10-17T10:26:00+08:00";
  for (let n = 0; n < (completed ? 30 : 18); n++) run = advanceRun(run);
  return run;
}
export function validStoredRun(value: unknown): value is DemoRun {
  try {
    const r = value as DemoRun;
    return (
      r.schemaVersion === 1 &&
      r.demo === true &&
      typeof r.id === "string" &&
      typeof r.createdAt === "string" &&
      Number.isFinite(Date.parse(r.createdAt)) &&
      Number.isInteger(r.revision) &&
      r.revision > 0 &&
      ["running", "cancelled", "failed", "completed"].includes(r.status) &&
      Array.isArray(r.snapshot.conditions) &&
      Array.isArray(r.snapshot.regions) &&
      Array.isArray(r.snapshot.entitySources) &&
      Array.isArray(r.snapshot.branches) &&
      Array.isArray(r.snapshot.groups) &&
      Array.isArray(r.snapshot.outputs) &&
      validateDocument(r.snapshot).length === 0 &&
      validateSettings(r.settings).length === 0 &&
      JSON.stringify(r.sampleTimes) ===
        JSON.stringify(sampleTimes(r.settings)) &&
      Number.isInteger(r.completedFrames) &&
      r.completedFrames >= 0 &&
      r.completedFrames <= r.sampleTimes.length &&
      Array.isArray(r.events) &&
      (r.status === "completed"
        ? r.completedFrames === r.sampleTimes.length
        : r.events.length === 0) &&
      r.resultAvailability ===
        (scriptAvailable(r.snapshot, r.settings)
          ? "scripted"
          : "not_provided") &&
      (r.status !== "completed" ||
        // A historical manual crop can differ from the latest thumbnail framing.
        // Validate it without rewriting it to the current seed.
        (r.events.every((event) =>
          event.evidence.every(
            (e) =>
              Array.isArray(e.crop) &&
              e.crop.length === 4 &&
              e.crop.every(Number.isFinite) &&
              e.crop[0] >= 0 &&
              e.crop[1] >= 0 &&
              e.crop[2] > 0 &&
              e.crop[3] > 0 &&
              e.crop[0] + e.crop[2] <= 1 &&
              e.crop[1] + e.crop[3] <= 1,
          ),
        ) &&
          JSON.stringify(eventIdentity(r.events)) ===
            JSON.stringify(eventIdentity(scriptedEvents(r)))))
    );
  } catch {
    return false;
  }
}
function eventIdentity(events: DemoEvent[]) {
  return events.map((event) => ({
    ...event,
    evidence: event.evidence.map(({ crop, ...evidence }) => evidence),
  }));
}
export function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const formatTime = (s: number) =>
  `${Math.floor(s / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(s % 60)
    .toString()
    .padStart(2, "0")}`;
