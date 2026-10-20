import { useEffect, useState } from "react";
import {
  RUN_STORAGE_KEY,
  exampleRun,
  validStoredRun,
  type DemoRun,
} from "./runs";

export function useDemoRuns(fixture: string) {
  const isolated = !!fixture;
  const [initial] = useState(() => {
    if (isolated)
      return {
        runs: fixture === "09" ? [] : [exampleRun(fixture === "11")],
        warning: false,
      };
    try {
      const raw = localStorage.getItem(RUN_STORAGE_KEY);
      if (!raw) return { runs: [] as DemoRun[], warning: false };
      const data = JSON.parse(raw);
      if (
        data.schemaVersion !== 1 ||
        !Array.isArray(data.runs) ||
        !data.runs.every(validStoredRun) ||
        new Set(data.runs.map((r: DemoRun) => r.id)).size !== data.runs.length
      )
        throw new Error("Invalid run archive");
      return { runs: data.runs as DemoRun[], warning: false };
    } catch {
      return { runs: [] as DemoRun[], warning: true };
    }
  });
  const [runs, setRuns] = useState(initial.runs);
  const [warning, setWarning] = useState(initial.warning);
  const [blocked, setBlocked] = useState(initial.warning);
  useEffect(() => {
    if (isolated || blocked) return;
    try {
      localStorage.setItem(
        RUN_STORAGE_KEY,
        JSON.stringify({ schemaVersion: 1, runs }),
      );
    } catch {
      setWarning(true);
    }
  }, [runs, isolated, blocked]);
  const saveBatch = (...updates: DemoRun[]) =>
    setRuns((prev) => [
      ...prev.filter((r) => !updates.some((item) => item.id === r.id)),
      ...updates,
    ]);
  const save = (run: DemoRun) => saveBatch(run);
  const reset = () => {
    setRuns([]);
    setWarning(false);
    setBlocked(false);
  };
  return { runs, save, saveBatch, warning, reset, isolated };
}
