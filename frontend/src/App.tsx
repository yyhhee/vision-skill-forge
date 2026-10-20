import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  CaretRightIcon,
  CheckCircleIcon,
  ColumnsIcon,
  DownloadSimpleIcon,
  ImageIcon,
  InfoIcon,
  PencilSimpleIcon,
  SquaresFourIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { AppShell } from "./components/AppShell";
import type { SceneEditGuard } from "./components/SceneViewport";
import {
  InspectorDrawer,
  createEditorForm,
  type EditorForm,
} from "./components/InspectorDrawer";
import { Button, Modal } from "./components/ui";
import { useWorkspace } from "./data/useWorkspace";
import { capabilityErrors } from "./data/capabilityRequirements";
import { useHistoryLeaveGuard } from "./data/navigation";
import {
  branchRegion,
  clone,
  conditionBranch,
  conditionLabel,
  validateDocument,
  type SkillDocument,
} from "./data/document";
import { applyEditorForm, newGroup } from "./data/editor";
import {
  regionDependents,
  validateIssues,
  type ValidationIssue,
} from "./data/validation";
import { SceneResources } from "./components/SceneResources";
import { IssuesPanel } from "./components/IssuesPanel";
const OrchestrationCanvas = lazy(() =>
  import("./components/OrchestrationCanvas").then((module) => ({
    default: module.OrchestrationCanvas,
  })),
);

type Dialog =
  | "unsaved"
  | "unsaved-region"
  | "issues"
  | "run"
  | "menu"
  | "later"
  | "delete-region"
  | null;
const SceneViewport = lazy(() =>
  import("./components/SceneViewport").then((module) => ({
    default: module.SceneViewport,
  })),
);
const RuleCanvas = lazy(() =>
  import("./components/RuleCanvas").then((module) => ({
    default: module.RuleCanvas,
  })),
);
const RunExperience = lazy(() =>
  import("./components/runs/RunExperience").then((module) => ({
    default: module.RunExperience,
  })),
);
const VersionExperience = lazy(() =>
  import("./components/versions/VersionExperience").then((module) => ({
    default: module.VersionExperience,
  })),
);
export function App({
  onOpenLibrary,
  onOpenModels,
  onOpenCapabilities,
  onOpenHistory,
}: {
  onOpenLibrary?: () => void;
  onOpenModels?: () => void;
  onOpenCapabilities?: () => void;
  onOpenHistory?: () => void;
} = {}) {
  const workspace = useWorkspace();
  const [capabilityNotice, setCapabilityNotice] = useState("");
  const { draft, applied, revision } = workspace.data;
  const [route] = useState(() => new URLSearchParams(location.search));
  const [runScreen, setRunScreen] = useState(
    () =>
      location.pathname.endsWith("/validate") ||
      location.pathname.startsWith("/runs/"),
  );
  const [versionScreen, setVersionScreen] = useState(() =>
    location.pathname.endsWith("/versions"),
  );
  const [selectedRegion, setSelectedRegion] = useState(
    route.get("fixture") === "03" || route.get("drawer") === "time"
      ? "roi-2"
      : "roi-1",
  );
  const [view, setView] = useState<
    "linked" | "canvas" | "scene" | "annotation" | "orchestration" | "outputs"
  >(
    route.get("view") === "scene"
      ? "annotation"
      : ((route.get("view") as "linked") ?? "linked"),
  );
  const [form, setForm] = useState<EditorForm | null>(() => {
    const kind = route.get("drawer");
    if (!kind || kind === "issues") return null;
    const id =
      kind === "condition"
        ? "a-red"
        : kind === "time"
          ? "branch-b"
          : kind === "group"
            ? draft.groups[0]?.id
            : draft.outputs[0].id;
    const next = createEditorForm(draft, id ?? "", kind);
    if (route.get("fixture") === "06")
      Object.assign(next, {
        timeMode: "continuous",
        duration: 5,
        gap: 0.5,
        scopeMode: "per_region",
        scopeSource: "roi-2",
      });
    return next;
  });
  const formInitial = useRef(
    form && route.get("fixture") === "06"
      ? JSON.stringify(createEditorForm(draft, "branch-b", "time"))
      : JSON.stringify(form),
  );
  const [dialog, setDialog] = useState<Dialog>(null);
  const [issues, setIssues] = useState<string[]>([]);
  const [laterLabel, setLaterLabel] = useState("");
  const [toast, setToast] = useState("");
  const [isNarrow, setIsNarrow] = useState(innerWidth < 1100);
  const pending = useRef<((saved?: SkillDocument) => void) | null>(null);
  const savedDocument = useRef(draft);
  savedDocument.current = draft;
  const [showIssues, setShowIssues] = useState(
    route.get("drawer") === "issues",
  );
  const [validated, setValidated] = useState(route.get("drawer") === "issues");
  const currentIssues = validateIssues(draft);
  const sceneGuard = useRef<SceneEditGuard>(null);
  const formDirty =
    form !== null && JSON.stringify(form) !== formInitial.current;
  useEffect(() => {
    if (workspace.screenshotMode || runScreen || versionScreen) return;
    const url = new URL(location.href);
    url.searchParams.set("view", view === "annotation" ? "scene" : view);
    if (form && form.kind !== "region")
      url.searchParams.set("drawer", form.kind);
    else if (showIssues) url.searchParams.set("drawer", "issues");
    else url.searchParams.delete("drawer");
    history.replaceState(history.state, "", url);
  }, [
    view,
    form?.kind,
    showIssues,
    workspace.screenshotMode,
    runScreen,
    versionScreen,
  ]);
  useEffect(() => {
    const resize = () => setIsNarrow(innerWidth < 1100);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (formDirty || sceneGuard.current?.isDirty()) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [formDirty]);
  const request = useCallback(
    (action: (saved?: SkillDocument) => void) => {
      if (formDirty) {
        pending.current = action;
        setDialog("unsaved");
      } else if (sceneGuard.current?.isDirty()) {
        pending.current = action;
        setDialog("unsaved-region");
      } else action();
    },
    [formDirty],
  );
  const edit = useCallback(
    (id: string, kind = "condition") =>
      request((saved) => {
        const current = saved ?? draft;
        const branchId =
          kind === "branch" || kind === "time"
            ? id
            : conditionBranch(current, id)?.id;
        const regionId = branchId && branchRegion(current, branchId);
        if (regionId) setSelectedRegion(regionId);
        const next = createEditorForm(current, id, kind);
        formInitial.current = JSON.stringify(next);
        setForm(next);
        setShowIssues(false);
      }),
    [draft, request],
  );
  const closeEditor = () => request(() => setForm(null));
  const saveEditor = (): boolean => {
    if (!form) return true;
    const next = applyEditorForm(draft, form);
    const previous = validateIssues(draft);
    const found = validateIssues(next)
      .filter(
        (issue) =>
          issue.code !== "evidence_review" &&
          (!previous.some(
            (old) =>
              old.target === issue.target &&
              old.kind === issue.kind &&
              old.message === issue.message,
          ) ||
            (issue.target ===
              (form.kind === "time" ? form.targetId : form.id) &&
              form.kind !== "region")),
      )
      .map((i) => i.message);
    if (!form.name.trim() && form.kind !== "description")
      found.push("名称不能为空。");
    if (found.length) {
      setIssues(found);
      setDialog("issues");
      return false;
    }
    workspace.commit(next);
    savedDocument.current = next;
    formInitial.current = JSON.stringify(form);
    setForm(null);
    setToast(
      validateIssues(next).some((issue) => issue.code === "evidence_review")
        ? "草稿已保存 · 自定义语义证据待核对，尚不能应用"
        : form.kind === "description"
          ? "技能说明已保存 · 检测规则未改变"
          : "已保存到草稿 · 当前运行快照未改变",
    );
    return true;
  };
  const apply = () =>
    request((saved) => {
      const current = saved ?? draft;
      const found = validateDocument(current);
      setValidated(true);
      if (found.length) {
        setForm(null);
        setShowIssues(true);
        return;
      }
      const unavailable = capabilityErrors(current, route.get("fixture") ?? "");
      if (unavailable.length) {
        setCapabilityNotice(unavailable.join(" "));
        return;
      }
      if (!workspace.dirty) {
        setToast(`当前运行 R${revision} 已是最新配置`);
        return;
      }
      workspace.apply(current);
      setShowIssues(false);
      setToast(`校验通过，已应用为运行 R${revision + 1}（本地演示快照）`);
    });
  const selectRegion = useCallback(
    (id: string) =>
      request((saved) => {
        setSelectedRegion(id);
        if (view === "annotation") {
          const next = createEditorForm(saved ?? draft, id, "region");
          formInitial.current = JSON.stringify(next);
          setForm(next);
        }
      }),
    [request, draft, view],
  );
  const switchView = (next: typeof view) =>
    request((saved) => {
      setView(next);
      setShowIssues(false);
      const doc = saved ?? draft;
      const nextForm =
        next === "annotation"
          ? createEditorForm(doc, selectedRegion, "region")
          : next === "outputs"
            ? createEditorForm(doc, doc.outputs[0].id, "output")
            : null;
      formInitial.current = JSON.stringify(nextForm);
      setForm(nextForm);
    });
  const addGroup = () =>
    request((saved) => {
      const next = clone(saved ?? draft);
      const group = newGroup(next);
      next.groups.push(group);
      workspace.commit(next);
      const f = createEditorForm(next, group.id, "group");
      formInitial.current = JSON.stringify(f);
      setForm(f);
    });
  const openTime = () =>
    edit(
      draft.branches.find((b) => branchRegion(draft, b.id) === selectedRegion)
        ?.id ?? draft.branches[0].id,
      "time",
    );
  const locateIssue = (issue: ValidationIssue) => {
    if (issue.kind === "region") {
      selectRegion(issue.target);
      switchView("annotation");
      const f = createEditorForm(draft, issue.target, "region");
      formInitial.current = JSON.stringify(f);
      setForm(f);
      setSelectedRegion(issue.target);
      setShowIssues(false);
    } else {
      if (issue.kind === "output") setView("outputs");
      edit(issue.target, issue.kind);
    }
  };
  const leaveForLibrary = (document?: SkillDocument) => {
    if (workspace.flush(document)) onOpenLibrary?.();
    else setToast("草稿尚未成功存入本地，请先导出备份；未离开编辑器。");
  };
  const continueHistory = (
    document: SkillDocument | undefined,
    proceed: () => void,
  ) => {
    if (workspace.historyOnly || workspace.flush(document)) proceed();
    else setToast("草稿尚未成功存入本地，请先导出备份；未离开编辑器。");
  };
  useHistoryLeaveGuard((proceed) => {
    if (
      runScreen ||
      versionScreen ||
      (!formDirty && !sceneGuard.current?.isDirty())
    )
      return false;
    request((saved) => continueHistory(saved, proceed));
    return true;
  });
  const later = (label: string) =>
    request((saved) => {
      if (label === "技能库" && onOpenLibrary) leaveForLibrary(saved);
      else if (label === "模型接入" && onOpenModels)
        continueHistory(saved, onOpenModels);
      else if (label === "能力管理" && onOpenCapabilities)
        continueHistory(saved, onOpenCapabilities);
      else if (label === "运行记录" && onOpenHistory)
        continueHistory(saved, onOpenHistory);
      else {
        setLaterLabel(label);
        setDialog("later");
      }
    });
  const exportDocument = () => {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            format: "vsf-frontend-demo",
            schemaVersion: 1,
            draft,
            applied,
            revision,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "vision-forge-workspace-demo.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setDialog(null);
  };
  const actualView =
    view === "annotation"
      ? "scene"
      : isNarrow && view === "linked"
        ? "scene"
        : view;
  const annotation = view === "annotation";
  const recheck = () =>
    request(() => {
      setForm(null);
      setValidated(true);
      setShowIssues(true);
    });
  const workspaceAction = (action: string) => {
    if (action === "时间约束") openTime();
    else if (action === "新增组") addGroup();
    else if (action === "业务输出") switchView("outputs");
    else if (action === "编排组") switchView("orchestration");
    else if (action === "检查配置") recheck();
    else if (action === "条件编辑")
      edit(
        draft.conditions.find((c) => c.kind === "visible_color")?.id ??
          draft.conditions[0].id,
      );
  };
  const openRunSetup = () =>
    request(() => {
      setDialog(null);
      setForm(null);
      setRunScreen(true);
    });
  const openVersions = () =>
    request(() => {
      setDialog(null);
      setForm(null);
      setShowIssues(false);
      setVersionScreen(true);
    });
  const returnToEditor = (doc = draft, loaded = false) => {
    const nextView = loaded
      ? doc.groups.length
        ? "orchestration"
        : "linked"
      : view;
    const url = new URL(location.href);
    url.pathname = `/skills/${encodeURIComponent(doc.id)}/editor`;
    url.searchParams.delete("drawer");
    url.searchParams.delete("state");
    url.searchParams.set(
      "view",
      nextView === "annotation" ? "scene" : nextView,
    );
    history.replaceState(history.state, "", url);
    setVersionScreen(false);
    setForm(null);
    setShowIssues(false);
    setView(nextView);
    if (loaded) setSelectedRegion(doc.regions[0]?.id ?? "");
  };
  if (versionScreen)
    return (
      <Suspense
        fallback={<main className="run-page">正在加载完整技能版本…</main>}
      >
        <VersionExperience
          draft={draft}
          applied={applied}
          revision={revision}
          workspaceDirty={workspace.dirty}
          fixture={route.get("fixture") ?? ""}
          onCommit={workspace.commit}
          onBack={() => returnToEditor()}
          onLibrary={onOpenLibrary ? leaveForLibrary : undefined}
          onHistoryLeave={continueHistory}
          onHistory={
            onOpenHistory
              ? (doc) => continueHistory(doc, onOpenHistory)
              : undefined
          }
          onCapabilities={
            onOpenCapabilities
              ? (doc) => continueHistory(doc, onOpenCapabilities)
              : undefined
          }
          onModels={
            onOpenModels
              ? (doc) => continueHistory(doc, onOpenModels)
              : undefined
          }
          onLoad={(doc, label) => {
            workspace.commit(doc);
            savedDocument.current = doc;
            returnToEditor(doc, true);
            setValidated(false);
            setToast(
              `已加载 ${label} 到草稿 · 当前运行 R${revision} 未改变，请校验并应用后运行`,
            );
          }}
        />
      </Suspense>
    );
  if (runScreen)
    return (
      <Suspense
        fallback={<main className="run-page">正在加载运行工作区…</main>}
      >
        <RunExperience
          draft={draft}
          applied={applied}
          revision={revision}
          workspaceDirty={workspace.dirty}
          fixture={route.get("fixture") ?? ""}
          onCommit={workspace.commit}
          onApply={(doc) => workspace.apply(doc)}
          onHistory={
            onOpenHistory
              ? (doc) => continueHistory(doc, onOpenHistory)
              : undefined
          }
          onCapabilities={
            onOpenCapabilities
              ? (doc) => continueHistory(doc, onOpenCapabilities)
              : undefined
          }
          onModels={
            onOpenModels
              ? (doc) => continueHistory(doc, onOpenModels)
              : undefined
          }
          onHistoryLeave={continueHistory}
          onLibrary={
            onOpenLibrary
              ? (doc) =>
                  workspace.historyOnly ? onOpenLibrary() : leaveForLibrary(doc)
              : undefined
          }
          onBack={() => {
            if (workspace.historyOnly && onOpenLibrary) {
              onOpenLibrary();
              return;
            }
            history.replaceState(
              history.state,
              "",
              `/skills/${draft.id}/editor?view=linked`,
            );
            setRunScreen(false);
            setView("linked");
            setForm(null);
          }}
        />
      </Suspense>
    );
  return (
    <AppShell
      dirty={workspace.dirty}
      revision={revision}
      onRun={() => request(() => setDialog("run"))}
      onMenu={() => request(() => setDialog("menu"))}
      onNavigate={later}
      title={draft.name}
      applyLabel={annotation ? "保存标注并继续" : "校验并应用"}
      onApply={
        annotation
          ? () =>
              request((saved) => {
                const current = saved ?? draft;
                if (validateIssues(current).some((i) => i.kind === "region")) {
                  setValidated(true);
                  setShowIssues(true);
                  return;
                }
                setView("linked");
                setForm(null);
              })
          : apply
      }
    >
      <main
        className="workspace"
        data-fixture={
          workspace.screenshotMode ? route.get("fixture") : "interactive"
        }
      >
        <nav className="workflow-steps" aria-label="技能创建步骤">
          {["创建", "场景（可选）", "编排", "验证"].map((label, index) => (
            <div
              key={label}
              className={index === (annotation ? 1 : 2) ? "current" : ""}
            >
              <button
                aria-current={
                  index === (annotation ? 1 : 2) ? "step" : undefined
                }
                onClick={() =>
                  index === 2
                    ? switchView("linked")
                    : index === 1
                      ? switchView("annotation")
                      : index === 3
                        ? openRunSetup()
                        : later(label)
                }
              >
                <span className="step-number">{index + 1}</span>
                <span>{label}</span>
              </button>
              {index < 3 && <CaretRightIcon size={19} />}
            </div>
          ))}
        </nav>
        <div className="instruction-bar">
          {annotation ? (
            <strong>为本技能标注检测区域，用于后续规则编排。</strong>
          ) : (
            <>
              <button
                className="instruction-edit"
                aria-label="编辑一句话描述"
                title="修改技能说明，不会重新编排；实际逻辑以规则画布为准"
                onClick={() => edit("description", "description")}
              >
                <strong>
                  <span className="description-marker">说明</span>
                  {draft.instruction}
                </strong>
                <PencilSimpleIcon size={20} />
              </button>
              <div className="view-switch" role="group" aria-label="工作区视图">
                <Button
                  icon={ColumnsIcon}
                  className={actualView === "linked" ? "selected-view" : ""}
                  onClick={() => switchView("linked")}
                >
                  联动编排
                </Button>
                <Button
                  icon={SquaresFourIcon}
                  className={actualView === "canvas" ? "selected-view" : ""}
                  onClick={() => switchView("canvas")}
                >
                  仅画布
                </Button>
                <Button
                  icon={ImageIcon}
                  className={actualView === "scene" ? "selected-view" : ""}
                  onClick={() => switchView("scene")}
                >
                  仅画面
                </Button>
              </div>
            </>
          )}
        </div>
        {validated && currentIssues.length > 0 && (
          <div className="validation-banner" role="alert">
            <WarningCircleIcon size={24} />
            <strong>校验未通过，{currentIssues.length}项问题需要处理。</strong>
            <Button onClick={() => setShowIssues(true)}>查看问题详情</Button>
          </div>
        )}
        <div
          className={`workspace-panels view-${actualView} ${annotation ? "scene-edit-layout" : ""}`}
          data-testid="workspace-panels"
        >
          {actualView !== "canvas" &&
            actualView !== "orchestration" &&
            actualView !== "outputs" && (
              <Suspense
                fallback={
                  <section className="panel" aria-label="场景加载中">
                    正在加载场景…
                  </section>
                }
              >
                <SceneViewport
                  ref={sceneGuard}
                  document={draft}
                  selectedRegion={selectedRegion}
                  onSelect={selectRegion}
                  onCommit={(doc) => {
                    savedDocument.current = doc;
                    workspace.commit(doc);
                  }}
                  onUndo={workspace.undo}
                  onRedo={workspace.redo}
                  canUndo={workspace.canUndo}
                  canRedo={workspace.canRedo}
                  onNotice={setToast}
                  screenshotMode={workspace.screenshotMode}
                  onRequest={request}
                  annotation={annotation}
                />
              </Suspense>
            )}
          {annotation && (
            <SceneResources
              document={draft}
              selected={selectedRegion}
              form={
                form?.kind === "region"
                  ? form
                  : createEditorForm(draft, selectedRegion, "region")
              }
              onChange={(f) => {
                if (form?.kind !== "region")
                  formInitial.current = JSON.stringify(
                    createEditorForm(draft, selectedRegion, "region"),
                  );
                setForm(f);
              }}
              onSelect={selectRegion}
              onSave={saveEditor}
              onDraw={(tool) => request(() => sceneGuard.current?.start(tool))}
              onAdd={() =>
                request(() => {
                  const next = clone(draft);
                  const id = `roi-${crypto.randomUUID()}`;
                  next.regions.push({
                    id,
                    name: `区域${draft.regions.length + 1}`,
                    type: "polygon",
                    colorIdentity: next.regions.length % 2 ? "teal" : "orange",
                    saved: false,
                    points: [],
                  });
                  workspace.commit(next);
                  setSelectedRegion(id);
                  const f = createEditorForm(next, id, "region");
                  formInitial.current = JSON.stringify(f);
                  setForm(f);
                })
              }
              onDelete={(id) =>
                request(() => {
                  const refs = regionDependents(draft, id);
                  setIssues(
                    refs.length
                      ? [
                          `此资源被以下条件或规则引用：${refs.join("、")}。请先解除引用，再删除。`,
                        ]
                      : ["删除后可使用撤销恢复。"],
                  );
                  if (refs.length) {
                    setDialog("issues");
                    return;
                  }
                  setLaterLabel(id);
                  setDialog("delete-region" as Dialog);
                })
              }
            />
          )}
          {actualView === "orchestration" && (
            <Suspense
              fallback={<section className="panel">正在加载编排画布…</section>}
            >
              <OrchestrationCanvas
                document={draft}
                onEdit={edit}
                onAdd={addGroup}
              />
            </Suspense>
          )}
          {actualView !== "scene" && actualView !== "orchestration" && (
            <Suspense
              fallback={
                <section className="panel" aria-label="画布加载中">
                  正在加载画布…
                </section>
              }
            >
              <RuleCanvas
                document={draft}
                selectedRegion={selectedRegion}
                onSelect={selectRegion}
                onEdit={edit}
                onAction={workspaceAction}
                outputMode={actualView === "outputs"}
              />
            </Suspense>
          )}
        </div>
        {view === "orchestration" && (
          <div className="workspace-secondary-actions">
            <Button
              onClick={() => edit(draft.groups[0]?.id ?? "", "group")}
              disabled={!draft.groups.length}
            >
              编辑已保存编排组
            </Button>
            <Button onClick={addGroup}>新增可复用编排组</Button>
            <Button onClick={() => switchView("outputs")}>
              下一步：业务输出
            </Button>
          </div>
        )}
        {form && form.kind !== "region" && (
          <InspectorDrawer
            form={form}
            document={draft}
            dirty={formDirty}
            onChange={setForm}
            onSave={saveEditor}
            onClose={closeEditor}
            onTimeTarget={(id) => edit(id, "time")}
            onEditTime={
              form.kind === "condition" || form.kind === "branch"
                ? () => edit(form.id, "time")
                : undefined
            }
          />
        )}
        {showIssues && (
          <IssuesPanel
            issues={currentIssues}
            revision={revision}
            onClose={() => setShowIssues(false)}
            onLocate={locateIssue}
            onRecheck={() => {
              setValidated(true);
              setToast(
                currentIssues.length
                  ? `仍有${currentIssues.length}项问题`
                  : "配置校验通过，可应用新版本",
              );
            }}
            onSnapshot={() => setDialog("run")}
          />
        )}
        {workspace.storageWarning && (
          <div className="storage-warning" role="alert">
            存储不可用或旧数据无效；未覆盖旧内容。当前修改暂存于内存，请导出备份。
          </div>
        )}
      </main>
      {toast && (
        <div className="toast" role="status">
          <CheckCircleIcon size={21} />
          {toast}
        </div>
      )}
      {dialog === "unsaved" && (
        <Modal
          title="当前表单尚未保存"
          onClose={() => {
            pending.current = null;
            setDialog(null);
          }}
          footer={
            <>
              <Button
                onClick={() => {
                  pending.current = null;
                  setDialog(null);
                }}
              >
                继续编辑
              </Button>
              <Button
                onClick={() => {
                  setForm(null);
                  if (sceneGuard.current?.isDirty()) {
                    setDialog("unsaved-region");
                    return;
                  }
                  setDialog(null);
                  const action = pending.current;
                  pending.current = null;
                  action?.(savedDocument.current);
                }}
              >
                放弃修改
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  if (saveEditor()) {
                    if (sceneGuard.current?.isDirty()) {
                      setDialog("unsaved-region");
                      return;
                    }
                    setDialog(null);
                    const action = pending.current;
                    pending.current = null;
                    action?.(savedDocument.current);
                  }
                }}
              >
                保存后继续
              </Button>
            </>
          }
        >
          <p>修改还未进入草稿，也不会影响当前运行版本。请选择如何处理。</p>
        </Modal>
      )}
      {dialog === "issues" && (
        <Modal
          title="配置需要修正"
          onClose={() => setDialog(null)}
          footer={
            <Button variant="primary" onClick={() => setDialog(null)}>
              返回修改
            </Button>
          }
        >
          <ul className="issues-list">
            {issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
          <p>草稿已保留，当前运行 R{revision} 未改变。</p>
        </Modal>
      )}
      {dialog === "delete-region" && (
        <Modal
          title="删除场景资源？"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>取消</Button>
              <Button
                variant="danger"
                onClick={() => {
                  const next = clone(draft);
                  next.regions = next.regions.filter(
                    (r) => r.id !== laterLabel,
                  );
                  workspace.commit(next);
                  setSelectedRegion(next.regions[0]?.id ?? "");
                  setForm(null);
                  setDialog(null);
                  setToast("已删除未被引用的资源，可撤销恢复。");
                }}
              >
                确认删除
              </Button>
            </>
          }
        >
          <p>仅删除所选未被引用的资源，不会更换其它条件的区域来源。</p>
        </Modal>
      )}
      {dialog === "unsaved-region" && (
        <Modal
          title="当前区域尚未保存"
          onClose={() => {
            pending.current = null;
            setDialog(null);
          }}
          footer={
            <>
              <Button
                onClick={() => {
                  pending.current = null;
                  setDialog(null);
                }}
              >
                继续绘制
              </Button>
              <Button
                onClick={() => {
                  sceneGuard.current?.discard();
                  setDialog(null);
                  const action = pending.current;
                  pending.current = null;
                  action?.();
                }}
              >
                放弃绘制
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  if (sceneGuard.current?.save(savedDocument.current)) {
                    setDialog(null);
                    const action = pending.current;
                    pending.current = null;
                    action?.(savedDocument.current);
                  }
                }}
              >
                保存后继续
              </Button>
            </>
          }
        >
          <p>绘制的点还没有进入草稿。请先保存或放弃，避免切换后丢失区域。</p>
        </Modal>
      )}
      {dialog === "run" && (
        <Modal
          title={revision ? `运行快照 R${revision}` : "尚未生成运行快照"}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>返回编排</Button>
              <Button
                variant="primary"
                disabled={revision === 0}
                onClick={openRunSetup}
              >
                打开运行设置
              </Button>
            </>
          }
        >
          <div className="notice">
            <InfoIcon size={22} />
            <span>
              可进入运行设置、模拟进度与结果证据页。仅演示前端交互，不调用模型；固定脚本结果不代表真实检测效果。
            </span>
          </div>
          <p>
            {revision
              ? "运行读取已应用快照，而非未应用草稿："
              : "请先校验并应用草稿，再查看运行快照。"}
          </p>
          {revision > 0 && (
            <ul>
              {applied.conditions
                .filter((c) => c.kind === "visible_color")
                .map((c) => (
                  <li key={c.id}>
                    {conditionLabel(c)} · 至少
                    {Math.round(c.minimumFraction! * 100)}%
                  </li>
                ))}
            </ul>
          )}
          {workspace.dirty && (
            <p className="warning-text">
              存在未应用修改；请先“校验并应用”再验证新规则。
            </p>
          )}
        </Modal>
      )}
      {dialog === "menu" && (
        <Modal title="工作台操作" onClose={() => setDialog(null)}>
          <div className="menu-actions">
            <Button onClick={openVersions}>完整技能与版本</Button>
            <div className="workspace-menu-grid">
              {[
                "场景标注",
                "条件编辑",
                "时间约束",
                "编排组",
                "业务输出",
                "检查配置",
              ].map((label) => (
                <Button
                  key={label}
                  onClick={() => {
                    setDialog(null);
                    if (label === "场景标注") switchView("annotation");
                    else workspaceAction(label);
                  }}
                >
                  {label}
                </Button>
              ))}
            </div>
            <Button icon={DownloadSimpleIcon} onClick={exportDocument}>
              导出完整演示配置
            </Button>
            <Button
              onClick={() => {
                workspace.reset();
                setForm(null);
                setSelectedRegion("roi-1");
                setDialog(null);
                setToast("已恢复本地演示基准，不影响原项目。");
              }}
            >
              恢复本地演示基准
            </Button>
            <p>
              运行 R{revision}
              、草稿与场景资源将一同导出。不包含模型凭证或真实运行数据。
            </p>
          </div>
        </Modal>
      )}
      {capabilityNotice && (
        <Modal
          title="依赖能力不可用"
          onClose={() => setCapabilityNotice("")}
          footer={
            <>
              <Button onClick={() => setCapabilityNotice("")}>返回编辑</Button>
              {onOpenCapabilities && (
                <Button
                  variant="primary"
                  onClick={() =>
                    request((saved) =>
                      continueHistory(saved, onOpenCapabilities),
                    )
                  }
                >
                  管理能力
                </Button>
              )}
            </>
          }
        >
          <p role="alert">{capabilityNotice}</p>
          <p>草稿、当前运行版本和历史记录未改变。</p>
        </Modal>
      )}
      {dialog === "later" && (
        <Modal
          title={laterLabel}
          onClose={() => setDialog(null)}
          footer={
            <Button variant="primary" onClick={() => setDialog(null)}>
              留在联动工作台
            </Button>
          }
        >
          <p>
            这个入口尚未提供。已有技能库、完整技能编辑与版本、运行记录、模型接入和能力管理可从侧栏进入；不会跳转到原服务或用其它内容替代。
          </p>
          <p>不会跳转到旧项目，也不会用相同结果假装其它页面已完成。</p>
        </Modal>
      )}
    </AppShell>
  );
}
