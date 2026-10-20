import { lazy, Suspense, useEffect, useState } from "react";
import { App } from "./App";
import { readSkill } from "./data/skillRepository";
import {
  builtInIds,
  readLibraryIndex,
  routeSkillId,
} from "./data/skillStorage";
import { Button } from "./components/ui";
import {
  HISTORY_INDEX,
  HISTORY_LEAVE_EVENT,
  ROUTE_EVENT,
  navigateLocal,
} from "./data/navigation";
const SkillLibrary = lazy(() =>
  import("./components/library/SkillLibrary").then((m) => ({
    default: m.SkillLibrary,
  })),
);
const SkillCreate = lazy(() =>
  import("./components/create/SkillCreate").then((m) => ({
    default: m.SkillCreate,
  })),
);
const ModelConnections = lazy(() =>
  import("./components/models/ModelConnections").then((m) => ({
    default: m.ModelConnections,
  })),
);
const CapabilityManagement = lazy(() =>
  import("./components/capabilities/CapabilityManagement").then((m) => ({
    default: m.CapabilityManagement,
  })),
);
const RunHistory = lazy(() =>
  import("./components/history/RunHistory").then((m) => ({
    default: m.RunHistory,
  })),
);

export function FrontendRoot() {
  const [route, setRoute] = useState(() => location.pathname + location.search);
  const [, refreshStorage] = useState(0);
  useEffect(() => {
    let currentIndex = Number(history.state?.[HISTORY_INDEX] ?? 0);
    history.replaceState(
      { ...history.state, [HISTORY_INDEX]: currentIndex },
      "",
    );
    let restoring = false,
      proceeding = false;
    const sync = () => {
      setRoute(location.pathname + location.search);
      refreshStorage((n) => n + 1);
    };
    const route = () => {
      currentIndex = Number(history.state?.[HISTORY_INDEX] ?? 0);
      sync();
    };
    const pop = () => {
      const targetIndex = history.state?.[HISTORY_INDEX];
      if (restoring) {
        restoring = false;
        return;
      }
      if (proceeding) {
        proceeding = false;
        currentIndex = targetIndex;
        sync();
        return;
      }
      const delta = Number(targetIndex) - currentIndex;
      if (typeof targetIndex === "number" && delta !== 0) {
        const event = new CustomEvent(HISTORY_LEAVE_EVENT, {
          cancelable: true,
          detail: {
            proceed: () => {
              proceeding = true;
              history.go(delta);
            },
          },
        });
        if (!window.dispatchEvent(event)) {
          restoring = true;
          history.go(-delta);
          return;
        }
      }
      currentIndex = Number(targetIndex ?? 0);
      sync();
    };
    window.addEventListener("popstate", pop);
    window.addEventListener(ROUTE_EVENT, route);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("popstate", pop);
      window.removeEventListener(ROUTE_EVENT, route);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const fixture = new URLSearchParams(location.search).get("fixture") ?? "";
  const libraryUrl = `/skills${fixture ? `?fixture=${encodeURIComponent(fixture)}` : ""}`;
  const modelsUrl = `/settings/models${fixture ? "?fixture=models" : ""}`;
  const capabilitiesUrl = `/settings/capabilities${fixture ? "?fixture=capabilities" : ""}`;
  const historyUrl = `/runs${fixture ? "?fixture=run-history" : ""}`;
  if (location.pathname === "/runs" || location.pathname === "/runs/")
    return (
      <Suspense fallback={<main className="run-page">正在加载运行记录…</main>}>
        <RunHistory key={fixture} fixture={fixture} navigate={navigateLocal} />
      </Suspense>
    );
  if (location.pathname === "/settings/capabilities")
    return (
      <Suspense fallback={<main className="run-page">正在加载能力管理…</main>}>
        <CapabilityManagement
          key={fixture}
          fixture={fixture}
          navigate={navigateLocal}
        />
      </Suspense>
    );
  if (location.pathname === "/settings/models")
    return (
      <Suspense fallback={<main className="run-page">正在加载模型配置…</main>}>
        <ModelConnections
          key={fixture}
          fixture={fixture}
          navigate={navigateLocal}
        />
      </Suspense>
    );
  if (location.pathname === "/skills/new")
    return (
      <Suspense fallback={<main className="run-page">正在加载创建页…</main>}>
        <SkillCreate fixture={fixture} navigate={navigateLocal} />
      </Suspense>
    );
  if (["/skills", "/skills/", "/"].includes(location.pathname))
    return (
      <Suspense fallback={<main className="run-page">正在加载技能库…</main>}>
        <SkillLibrary
          key={route.split("?")[0]}
          fixture={fixture}
          startCreating={
            new URLSearchParams(location.search).get("create") === "template"
          }
          navigate={navigateLocal}
        />
      </Suspense>
    );
  if (
    !/^\/skills\/[^/]+\/(?:editor|validate|versions)\/?$/.test(
      location.pathname,
    ) &&
    !/^\/runs\/[^/]+\/?$/.test(location.pathname)
  )
    return (
      <main className="fatal-error">
        <h1>这个页面尚未实现</h1>
        <p>
          当前只提供技能库、完整技能编辑、版本与单次模拟运行，不会用区域告警工作区冒充其它页面。
        </p>
        <Button onClick={() => navigateLocal(libraryUrl)}>返回技能库</Button>
      </main>
    );
  const skillId = routeSkillId();
  if (!fixture && !location.pathname.startsWith("/runs/")) {
    let error = "";
    try {
      if (readLibraryIndex().removed.includes(skillId))
        error = "这个本地技能已删除，历史运行记录仍保留。";
      else if (!builtInIds.includes(skillId)) {
        const data = readSkill(skillId);
        if (data.draft.mediaRef !== "construction-poster")
          error =
            "该技能的素材尚未接入本前端，配置和版本仍保留，可在技能库导出。不会用施工海报冒充它的素材。";
      }
    } catch (e) {
      if (!builtInIds.includes(skillId)) error = (e as Error).message;
    }
    if (error)
      return (
        <main className="fatal-error">
          <h1>暂不能打开这个技能</h1>
          <p role="alert">{error}</p>
          <Button onClick={() => navigateLocal(libraryUrl)}>返回技能库</Button>
        </main>
      );
  }
  return (
    <App
      key={skillId + fixture}
      onOpenLibrary={() => navigateLocal(libraryUrl)}
      onOpenModels={() => navigateLocal(modelsUrl)}
      onOpenCapabilities={() => navigateLocal(capabilitiesUrl)}
      onOpenHistory={() => navigateLocal(historyUrl)}
    />
  );
}
