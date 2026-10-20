import { beforeEach, expect, it } from "vitest";
import {
  dateRangeError,
  emptyHistoryFilter,
  filterHistory,
  fixtureHistory,
  historyDate,
  historyRoute,
  historyExport,
  readRunArchive,
  rowFromRun,
} from "../../src/data/runHistory";
import {
  RUN_STORAGE_KEY,
  exampleRun,
  createRun,
  advanceRun,
} from "../../src/data/runs";
import { seedWorkspace } from "../../src/data/document";
beforeEach(() => localStorage.clear());
it("route filters round trip without depending on browser cache or accepting arbitrary enum values", () => {
  const parsed = historyRoute(
    "?q=%E5%8C%BA%E5%9F%9F&status=failed&media=image&range=custom&from=2026-10-16&to=2026-10-17&page=2&selected=record-1&skill=regional-alert",
  );
  expect(parsed).toMatchObject({
    page: 2,
    selected: "record-1",
    filter: {
      search: "区域",
      skillId: "regional-alert",
      status: "failed",
      media: "image",
      range: { mode: "custom", from: "2026-10-16", to: "2026-10-17" },
    },
  });
  expect(historyRoute("?page=-1&status=bogus&media=script")).toMatchObject({
    page: 1,
    filter: { status: "all", media: "all" },
  });
});
it("normal history starts empty and reading never seeds or writes archives", () => {
  expect(readRunArchive()).toEqual({ runs: [], raw: null });
  expect(localStorage.length).toBe(0);
  const raw = JSON.stringify({ schemaVersion: 1, runs: [exampleRun(true)] });
  localStorage.setItem(RUN_STORAGE_KEY, raw);
  expect(readRunArchive().runs[0].events).toHaveLength(1);
  expect(localStorage.getItem(RUN_STORAGE_KEY)).toBe(raw);
});
it("corrupt, blank, incompatible and duplicate archives remain untouched and fail closed", () => {
  const r = exampleRun(true);
  for (const raw of [
    "",
    "broken",
    "null",
    '{"schemaVersion":2,"runs":[]}',
    JSON.stringify({ schemaVersion: 1, runs: [r, r] }),
    JSON.stringify({ schemaVersion: 1, runs: [{ ...r, id: "" }] }),
    JSON.stringify({ schemaVersion: 1, runs: [{ ...r, snapshot: {} }] }),
  ]) {
    localStorage.setItem(RUN_STORAGE_KEY, raw);
    expect(() => readRunArchive()).toThrow("原内容未覆盖");
    expect(localStorage.getItem(RUN_STORAGE_KEY)).toBe(raw);
  }
});
it("isolated five-row fixture has only one real detailed snapshot and never assigns fake R to summaries", () => {
  const rows = fixtureHistory();
  expect(rows).toHaveLength(5);
  expect(rows.filter((r) => r.run)).toHaveLength(1);
  expect(rows[0].createdAt).toBe(exampleRun(true).createdAt);
  rows.slice(1).forEach((r) => expect(r.revision).toBeNull());
  expect(localStorage.length).toBe(0);
});
it("all filters intersect and time zones use Beijing dates including inclusive last day", () => {
  const rows = fixtureHistory(),
    f = emptyHistoryFilter();
  expect(filterHistory(rows, f)).toHaveLength(5);
  expect(
    filterHistory(rows, { ...f, status: "completed", media: "image" }).map(
      (r) => r.skillId,
    ),
  ).toEqual(["furniture"]);
  expect(
    filterHistory(rows, { ...f, skillId: "regional-alert", search: "R3" }),
  ).toHaveLength(1);
  expect(
    filterHistory(rows, {
      ...f,
      range: { mode: "custom", from: "2026-10-16", to: "2026-10-16" },
    }),
  ).toHaveLength(2);
  expect(historyDate("2026-10-16T16:00:00Z")).toEqual({
    day: "2026-10-17",
    time: "00:00",
  });
  expect(
    filterHistory(
      rows,
      { ...f, range: { mode: "today", from: "", to: "" } },
      Date.parse("2026-10-17T12:00:00+08:00"),
    ),
  ).toHaveLength(3);
  expect(
    filterHistory(
      rows,
      { ...f, range: { mode: "week", from: "", to: "" } },
      Date.parse("2026-10-23T12:00:00+08:00"),
    ),
  ).toHaveLength(3);
});
it("invalid custom ranges cannot match all or silently broaden the filter", () => {
  for (const range of [
    { mode: "custom" as const, from: "", to: "" },
    { mode: "custom" as const, from: "2026-02-30", to: "2026-03-01" },
    { mode: "custom" as const, from: "2026-10-18", to: "2026-10-17" },
  ]) {
    expect(dateRangeError(range)).not.toBe("");
    expect(
      filterHistory(fixtureHistory(), { ...emptyHistoryFilter(), range }),
    ).toEqual([]);
  }
});
it("not-provided results and unfinished tasks do not imply zero detections", () => {
  let run = createRun(
    { ...seedWorkspace().applied, name: "other configuration" },
    4,
  );
  expect(rowFromRun(run).eventCount).toBeNull();
  while (run.status === "running") run = advanceRun(run);
  expect(rowFromRun(run).eventCount).toBeNull();
  expect(rowFromRun(run).evidenceCount).toBeNull();
  expect(rowFromRun(exampleRun(true)).evidenceCount).toBe(2);
});
it("unknown media never borrows a known poster and exports preserve full immutable snapshots", () => {
  const doc = { ...seedWorkspace().applied, mediaRef: "foreign-video" },
    run = createRun(doc, 4);
  const row = rowFromRun(run);
  expect(row.thumbnail).toBeUndefined();
  expect(row.media).toBe("unknown");
  const exported = historyExport(row) as typeof run;
  expect(exported).toEqual(run);
  exported.snapshot.name = "changed export";
  expect(run.snapshot.name).toBe(doc.name);
  const summary = historyExport(fixtureHistory()[1]);
  expect(summary).toMatchObject({
    snapshotIncluded: false,
    detailsAvailable: false,
  });
  expect(summary).not.toHaveProperty("snapshot");
});
