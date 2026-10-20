import { describe, expect, it } from "vitest";
import { clone, seedWorkspace } from "../../src/data/document";
import {
  advanceRun,
  cancelRun,
  createRun,
  exampleRun,
  failRun,
  readSettings,
  sampleTimes,
  scriptAvailable,
  validStoredRun,
  validateSettings,
} from "../../src/data/runs";

describe("frontend simulation contract", () => {
  it("keeps bounded historical thumbnail crops without rewriting the saved run", () => {
    const run = exampleRun(true);
    run.events[0].evidence[0].crop = [0.17, 0.465, 0.09, 0.12];
    expect(validStoredRun(run)).toBe(true);
    expect(run.events[0].evidence[0].crop[1]).toBe(0.465);
    run.events[0].evidence[0].crop = [0.9, 0.9, 0.2, 0.2];
    expect(validStoredRun(run)).toBe(false);
  });
  it("sampling uses half-open time range, not model request counts", () => {
    const s = readSettings(seedWorkspace().applied);
    expect(sampleTimes(s)).toEqual(Array.from({ length: 30 }, (_, i) => i));
    expect(sampleTimes({ ...s, maxFrames: 3 })).toEqual([0, 1, 2]);
    expect(sampleTimes({ ...s, sampleIntervalSeconds: 2 })).toHaveLength(15);
  });
  it.each([0, -1, NaN, Infinity])(
    "rejects invalid sampling interval %s",
    (value) => {
      const s = readSettings(seedWorkspace().applied);
      s.sampleIntervalSeconds = value;
      expect(validateSettings(s).length).toBeGreaterThan(0);
      expect(sampleTimes(s)).toEqual([]);
    },
  );
  it("validates geometry-independent runtime configuration", () => {
    const s = readSettings(seedWorkspace().applied);
    s.tiles.width = 127;
    s.tiles.overlapY = 1;
    s.dedup.threshold = NaN;
    expect(validateSettings(s)).toHaveLength(3);
  });
  it("start clones applied document and settings instead of retaining references", () => {
    const doc = seedWorkspace().applied;
    const run = createRun(doc, 3);
    doc.conditions[1].minimumFraction = 0.9;
    (doc.runSettings as { tiles: { width: number } }).tiles.width = 2048;
    expect(run.snapshot.conditions[1].minimumFraction).toBe(0.2);
    expect(run.settings.tiles.width).toBe(640);
  });
  it("only explicit supported snapshot and sampled event point get scripted results", () => {
    const { draft, applied } = seedWorkspace();
    expect(scriptAvailable(applied, readSettings(applied))).toBe(true);
    expect(scriptAvailable(draft, readSettings(draft))).toBe(false);
    expect(
      scriptAvailable(applied, { ...readSettings(applied), endSeconds: 10 }),
    ).toBe(false);
  });
  it("cancel is terminal and never yields completed events", () => {
    const cancelled = cancelRun(exampleRun());
    expect(cancelled.status).toBe("cancelled");
    expect(cancelled.completedFrames).toBe(18);
    expect(advanceRun(cancelled)).toBe(cancelled);
    expect(cancelled.events).toEqual([]);
  });
  it("failed is terminal, distinct from empty successful results", () => {
    const failed = failRun(exampleRun());
    expect(failed.status).toBe("failed");
    expect(failed.error).toMatch(/模拟失败/);
    expect(advanceRun(failed)).toBe(failed);
    expect(failed.events).toEqual([]);
  });
  it("complete known script binds event and both pieces of evidence to same entity", () => {
    const run = exampleRun(true);
    expect(run.completedFrames).toBe(30);
    expect(run.events).toHaveLength(1);
    expect(run.events[0].evidence.map((e) => e.entityId)).toEqual([
      "person-1",
      "person-1",
    ]);
    expect(validStoredRun(run)).toBe(true);
  });
  it("complete a modified rule without inventing a result", () => {
    const doc = seedWorkspace().draft;
    let run = createRun(doc, 4);
    for (let i = 0; i < 30; i++) run = advanceRun(run);
    expect(run.status).toBe("completed");
    expect(run.resultAvailability).toBe("not_provided");
    expect(run.events).toEqual([]);
    expect(validStoredRun(run)).toBe(true);
  });
  it("stored runs reject tampering, invalid progress, partial and foreign objects", () => {
    expect(validStoredRun(null)).toBe(false);
    expect(validStoredRun({})).toBe(false);
    const run = exampleRun(true);
    const tampered = clone(run);
    tampered.events[0].name = "fake";
    expect(validStoredRun(tampered)).toBe(false);
    expect(validStoredRun({ ...run, completedFrames: 29 })).toBe(false);
    expect(validStoredRun({ ...run, demo: false })).toBe(false);
    expect(validStoredRun({ ...run, sampleTimes: [0, 1] })).toBe(false);
  });
});
