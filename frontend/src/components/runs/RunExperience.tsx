import { useEffect, useRef, useState } from "react";
import {
  ArrowLeftIcon,
  DownloadSimpleIcon,
  PlayIcon,
  StopCircleIcon,
} from "@phosphor-icons/react";
import { AppShell } from "../AppShell";
import { Button, Modal } from "../ui";
import {
  clone,
  validateDocument,
  type SkillDocument,
} from "../../data/document";
import {
  advanceRun,
  cancelRun,
  createRun,
  downloadJson,
  exampleRun,
  failRun,
  readSettings,
  validateSettings,
  type DemoRun,
  type RunSettings,
} from "../../data/runs";
import { useDemoRuns } from "../../data/useDemoRuns";
import { capabilityErrors } from "../../data/capabilityRequirements";
import { useHistoryLeaveGuard } from "../../data/navigation";
import { RunSetup } from "./RunSetup";
import { RunMonitor } from "./RunMonitor";
import { ResultExplorer } from "./ResultExplorer";

type PageMode = "setup" | "monitor" | "results";
type Dialog =
  | "unsaved"
  | "apply"
  | "snapshot"
  | "edit"
  | "cancel"
  | "storage"
  | "other"
  | "active-version"
  | null;
export function RunExperience({
  draft,
  applied,
  revision,
  workspaceDirty,
  fixture,
  onCommit,
  onApply,
  onBack,
  onLibrary,
  onHistoryLeave,
  onModels,
  onCapabilities,
  onHistory,
}: {
  draft: SkillDocument;
  applied: SkillDocument;
  revision: number;
  workspaceDirty: boolean;
  fixture: string;
  onCommit: (doc: SkillDocument) => void;
  onApply: (doc: SkillDocument) => void;
  onBack: () => void;
  onLibrary?: (doc?: SkillDocument) => void;
  onModels?: (doc?: SkillDocument) => void;
  onCapabilities?: (doc?: SkillDocument) => void;
  onHistory?: (doc?: SkillDocument) => void;
  onHistoryLeave?: (
    doc: SkillDocument | undefined,
    proceed: () => void,
  ) => void;
}) {
  const store = useDemoRuns(fixture);
  const [initialId] = useState(() =>
    location.pathname.startsWith("/runs/")
      ? decodeURIComponent(location.pathname.split("/")[2])
      : "",
  );
  const [run, setRun] = useState<DemoRun | null>(() => {
    if (fixture === "10" || fixture === "11")
      return exampleRun(fixture === "11");
    const stored = store.runs.find((r) => r.id === initialId);
    if (stored) return stored;
    if (fixture && initialId === "run-regional-r3")
      return exampleRun(
        new URLSearchParams(location.search).get("state") !== "running",
      );
    return null;
  });
  const [mode, setMode] = useState<PageMode>(
    initialId ? (run?.status === "completed" ? "results" : "monitor") : "setup",
  );
  const [settings, setSettings] = useState<RunSettings>(() =>
    readSettings(applied),
  );
  const baseline = useRef(JSON.stringify(settings));
  const dirty = JSON.stringify(settings) !== baseline.current;
  const [playing, setPlaying] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState("");
  const [other, setOther] = useState("");
  const [activeChoice, setActiveChoice] = useState<{
    active: DemoRun;
    requested: SkillDocument;
    revision: number;
  } | null>(null);
  const pending = useRef<(() => void) | null>(null);
  const appliedJson = JSON.stringify(applied);
  useEffect(() => {
    const previous = document.title;
    return () => {
      document.title = previous;
    };
  }, []);
  useEffect(() => {
    document.title = `Vision Skill Forge · ${mode === "setup" ? "验证配置" : mode === "results" ? "结果与证据" : "模拟运行进度"}`;
  }, [mode]);
  useEffect(() => {
    const s = readSettings(applied);
    setSettings(s);
    baseline.current = JSON.stringify(s);
  }, [appliedJson]);
  useEffect(() => {
    if (store.isolated) return;
    if (mode === "setup")
      history.replaceState(history.state, "", `/skills/${applied.id}/validate`);
    else if (run)
      history.replaceState(
        history.state,
        "",
        `/runs/${encodeURIComponent(run.id)}?state=${run.status}`,
      );
  }, [mode, run?.id, run?.status, store.isolated, applied.id]);
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  const publish = (next: DemoRun) => {
    setRun(next);
    store.save(next);
  };
  const available = (doc: SkillDocument) => {
    const issues = capabilityErrors(doc, fixture);
    if (issues.length) {
      setPlaying(false);
      setError(issues.join(" "));
      return false;
    }
    return true;
  };
  useEffect(() => {
    if (
      !playing ||
      mode !== "monitor" ||
      run?.status !== "running" ||
      store.isolated
    )
      return;
    const timer = setTimeout(() => {
      if (available(run.snapshot)) publish(advanceRun(run));
    }, 350);
    return () => clearTimeout(timer);
  }, [playing, mode, run, store.isolated]);
  useEffect(() => {
    if (run?.status !== "running") setPlaying(false);
  }, [run?.status]);
  const saveSettings = () => {
    const errors = validateSettings(settings);
    if (errors.length) {
      setError(errors.join(" "));
      return false;
    }
    onCommit({ ...clone(draft), runSettings: clone(settings) });
    baseline.current = JSON.stringify(settings);
    setError("");
    return true;
  };
  const request = (action: () => void) => {
    if (dirty) {
      pending.current = action;
      setDialog("unsaved");
    } else action();
  };
  useHistoryLeaveGuard((proceed) => {
    if (!dirty) return false;
    request(() => {
      const doc =
        JSON.stringify(settings) === baseline.current
          ? { ...clone(draft), runSettings: clone(settings) }
          : draft;
      if (onHistoryLeave) onHistoryLeave(doc, proceed);
      else proceed();
    });
    return true;
  });
  const back = () =>
    request(() => {
      setPlaying(false);
      if (mode !== "setup" && run) {
        setDialog("edit");
      } else onBack();
    });
  const start = () =>
    request(() => {
      if (revision < 1 || validateDocument(applied).length) {
        setError("请先返回编排，校验并应用一个有效版本。");
        return;
      }
      const active = store.runs.find((r) => r.status === "running");
      if (!available(applied)) return;
      if (active) {
        if (
          active.revision !== revision ||
          active.snapshot.id !== applied.id ||
          JSON.stringify(active.snapshot) !== JSON.stringify(applied)
        ) {
          setActiveChoice({ active, requested: clone(applied), revision });
          setPlaying(false);
          setError("");
          setDialog("active-version");
          return;
        }
        setRun(active);
        setMode("monitor");
        setPlaying(false);
        setError("已打开尚未结束的模拟任务；请继续或取消，不会重复新建。");
        return;
      }
      try {
        const next = createRun(applied, revision);
        publish(next);
        setMode("monitor");
        setPlaying(!store.isolated);
        setError("");
      } catch (e) {
        setError((e as Error).message);
      }
    });
  const replaceActive = () => {
    if (!activeChoice) return;
    const active = store.runs.find(
      (item) => item.id === activeChoice.active.id && item.status === "running",
    );
    if (
      !active ||
      revision !== activeChoice.revision ||
      JSON.stringify(applied) !== JSON.stringify(activeChoice.requested)
    ) {
      setDialog(null);
      setActiveChoice(null);
      setError(
        "配置或旧任务状态已变化，请重新点击开始并确认版本。未停止或新建任何任务。",
      );
      return;
    }
    try {
      // Construct and validate before cancelling; publish both records together.
      if (!available(applied)) return;
      const next = createRun(applied, revision);
      store.saveBatch(cancelRun(active), next);
      setRun(next);
      setMode("monitor");
      setPlaying(!store.isolated);
      setDialog(null);
      setActiveChoice(null);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const openPrevious = () =>
    request(() => {
      const previous = store.runs[store.runs.length - 1];
      if (previous) {
        setRun(previous);
        setMode(previous.status === "completed" ? "results" : "monitor");
        setPlaying(false);
      }
    });
  const apply = () => {
    const next = { ...clone(draft), runSettings: clone(settings) };
    const errors = [
      ...validateSettings(settings),
      ...validateDocument(next),
      ...capabilityErrors(next, fixture),
    ];
    if (errors.length) {
      setError(errors.join(" "));
      return;
    }
    onApply(next);
    baseline.current = JSON.stringify(settings);
    setDialog(null);
    setError("");
  };
  const actions = (
    <>
      <Button icon={ArrowLeftIcon} onClick={back}>
        {mode === "setup" ? "返回编排" : "返回规则"}
      </Button>
      {mode === "setup" ? (
        <Button
          icon={PlayIcon}
          variant="primary"
          disabled={revision < 1}
          onClick={start}
        >
          开始模拟验证
        </Button>
      ) : run?.status === "running" ? (
        <Button
          variant="danger"
          icon={StopCircleIcon}
          onClick={() => {
            setPlaying(false);
            setDialog("cancel");
          }}
        >
          停止本次模拟
        </Button>
      ) : run?.status === "completed" ? (
        <Button
          variant="primary"
          icon={DownloadSimpleIcon}
          onClick={() => downloadJson(run, `${run.id}-demo-result.json`)}
        >
          导出结果
        </Button>
      ) : (
        <Button onClick={() => setMode("setup")}>返回运行设置</Button>
      )}
    </>
  );
  return (
    <AppShell
      dirty={false}
      revision={mode === "setup" ? revision : (run?.revision ?? 0)}
      title={
        mode === "setup" ? applied.name : (run?.snapshot.name ?? "运行记录")
      }
      activeNavigation={mode === "setup" ? "技能库" : "运行记录"}
      statusLabel={
        mode === "setup"
          ? revision > 0
            ? `使用已应用 R${revision}`
            : "尚未生成运行快照"
          : `使用版本 R${run?.revision ?? "—"} · 模拟${run?.status === "completed" ? "结果" : "任务"}`
      }
      actions={actions}
      onRun={start}
      onApply={() => {}}
      onMenu={() => {}}
      onNavigate={(label) => {
        if (label === "运行记录" && onHistory) {
          request(() => {
            setPlaying(false);
            onHistory(
              JSON.stringify(settings) === baseline.current
                ? { ...clone(draft), runSettings: clone(settings) }
                : draft,
            );
          });
          return;
        }
        if (label === "能力管理" && onCapabilities) {
          request(() => {
            setPlaying(false);
            onCapabilities(
              JSON.stringify(settings) === baseline.current
                ? { ...clone(draft), runSettings: clone(settings) }
                : draft,
            );
          });
          return;
        }
        if (label === "模型接入" && onModels) {
          request(() => {
            setPlaying(false);
            onModels(
              JSON.stringify(settings) === baseline.current
                ? { ...clone(draft), runSettings: clone(settings) }
                : draft,
            );
          });
          return;
        }
        if (label === "技能库" && onLibrary)
          request(() => {
            setPlaying(false);
            onLibrary(
              JSON.stringify(settings) === baseline.current
                ? { ...clone(draft), runSettings: clone(settings) }
                : draft,
            );
          });
        else if (label === "技能库") back();
        else
          request(() => {
            setOther(label);
            setDialog("other");
          });
      }}
    >
      {mode === "setup" ? (
        <RunSetup
          document={applied}
          revision={revision}
          settings={settings}
          dirty={dirty}
          workspaceDirty={workspaceDirty}
          onChange={setSettings}
          onSave={saveSettings}
          onApply={() => setDialog("apply")}
          onBack={back}
          onPrevious={store.runs.length ? openPrevious : undefined}
        />
      ) : run ? (
        mode === "results" && run.status === "completed" ? (
          <ResultExplorer
            key={run.id}
            run={run}
            onSnapshot={() => setDialog("snapshot")}
            onEdit={back}
          />
        ) : (
          <RunMonitor
            run={run}
            playing={playing}
            frozen={store.isolated}
            onPlaying={(next) => {
              if (!next || available(run.snapshot)) setPlaying(next);
            }}
            onAdvance={() => {
              if (available(run.snapshot)) publish(advanceRun(run));
            }}
            onFail={() => {
              publish(failRun(run));
              setPlaying(false);
            }}
            onResults={() => setMode("results")}
          />
        )
      ) : (
        <main className="run-page">
          <div className="panel run-card">
            <h1>未找到该运行记录</h1>
            <p>未提供该标识的结果，不会替换成其它任务。</p>
            <Button onClick={() => setMode("setup")}>返回运行设置</Button>
          </div>
        </main>
      )}
      {error && (
        <div className="run-floating-message" role="alert">
          {error}
          <Button onClick={() => setError("")}>知道了</Button>
        </div>
      )}
      {store.warning && (
        <div className="run-floating-message" role="alert">
          运行记录存储不可用或损坏；未覆盖旧内容。请导出当前结果。
          <Button onClick={() => setDialog("storage")}>管理记录缓存</Button>
        </div>
      )}
      {dialog === "unsaved" && (
        <Modal
          title="运行设置尚未保存"
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
                  setSettings(readSettings(applied));
                  baseline.current = JSON.stringify(readSettings(applied));
                  setDialog(null);
                  const action = pending.current;
                  pending.current = null;
                  action?.();
                }}
              >
                放弃修改
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  if (saveSettings()) {
                    setDialog(null);
                    const action = pending.current;
                    pending.current = null;
                    action?.();
                  }
                }}
              >
                保存后继续
              </Button>
            </>
          }
        >
          <p>
            保存只进入草稿。若继续运行，将使用已应用R{revision}
            中的设置，而不是未应用设置。
          </p>
        </Modal>
      )}
      {dialog === "apply" && (
        <Modal
          title="应用全部草稿修改？"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>取消</Button>
              <Button variant="primary" onClick={apply}>
                校验并应用为 R{revision + 1}
              </Button>
            </>
          }
        >
          <p>
            将运行设置和当前草稿的条件、时间、编排、输出一起应用为R
            {revision + 1}，不是仅更新本页设置。
          </p>
          <p>已有运行和结果仍保留原快照，不会被改写。</p>
        </Modal>
      )}
      {dialog === "active-version" && activeChoice && (
        <Modal
          title="选择要验证的版本"
          onClose={() => {
            setDialog(null);
            setActiveChoice(null);
          }}
          footer={
            <>
              <Button
                onClick={() => {
                  setDialog(null);
                  setActiveChoice(null);
                }}
              >
                取消
              </Button>
              <Button
                onClick={() => {
                  const active = store.runs.find(
                    (item) =>
                      item.id === activeChoice.active.id &&
                      item.status === "running",
                  );
                  if (active) {
                    if (!available(active.snapshot)) {
                      setDialog(null);
                      setActiveChoice(null);
                      return;
                    }
                    setRun(active);
                    setMode("monitor");
                    setPlaying(!store.isolated);
                    setError("");
                  } else setError("旧任务状态已变化，请重新选择。未新建任务。");
                  setDialog(null);
                  setActiveChoice(null);
                }}
              >
                继续旧任务 R{activeChoice.active.revision}
              </Button>
              <Button variant="primary" onClick={replaceActive}>
                停止旧任务并新建 R{activeChoice.revision}
              </Button>
            </>
          }
        >
          <p>
            准备验证：{activeChoice.requested.name} · R{activeChoice.revision}。
          </p>
          <p>
            尚未结束：{activeChoice.active.snapshot.name} · R
            {activeChoice.active.revision}（已完成{" "}
            {activeChoice.active.completedFrames}/
            {activeChoice.active.sampleTimes.length} 个采样点）。
          </p>
          <p>
            继续旧任务不会使用新配置；停止后新建会保留旧任务及其快照，状态记为已取消，不会改写为新版本。
          </p>
        </Modal>
      )}
      {dialog === "cancel" && (
        <Modal
          title="停止本次模拟？"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>继续运行</Button>
              <Button
                variant="danger"
                onClick={() => {
                  if (run) publish(cancelRun(run));
                  setPlaying(false);
                  setDialog(null);
                }}
              >
                确认停止
              </Button>
            </>
          }
        >
          <p>停止后状态为“已取消”，不是“已完成”；不会产生示例业务事件。</p>
        </Modal>
      )}
      {dialog === "edit" && run && (
        <Modal
          title="选择要查看的配置"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog("snapshot")}>
                查看本次运行快照
              </Button>
              <Button variant="primary" onClick={onBack}>
                编辑当前草稿
              </Button>
            </>
          }
        >
          <p>
            本次结果绑定R{run.revision}。当前工作区已应用R{revision}
            {workspaceDirty ? "，另有未应用草稿" : ""}。
          </p>
          <p>
            编辑草稿不会修改本次结果。需要验证新规则时，请应用后另建模拟运行。
          </p>
        </Modal>
      )}
      {dialog === "snapshot" && run && (
        <Modal
          title={`本次运行快照 R${run.revision}（只读）`}
          onClose={() => setDialog(null)}
          footer={
            <Button
              onClick={() =>
                downloadJson(run.snapshot, `${run.id}-snapshot.json`)
              }
            >
              导出本次快照
            </Button>
          }
        >
          <p>{run.snapshot.instruction}</p>
          <ul>
            {run.snapshot.conditions.map((c) => (
              <li key={c.id}>
                {c.label}
                {c.minimumFraction !== undefined
                  ? ` · 至少${c.minimumFraction * 100}%`
                  : ""}
              </li>
            ))}
          </ul>
          <p>
            采样间隔{run.settings.sampleIntervalSeconds}秒 ·{" "}
            {run.sampleTimes.length}个点
          </p>
          <p>仅查看本次快照，不加载、不应用到当前草稿。</p>
        </Modal>
      )}
      {dialog === "storage" && (
        <Modal
          title="清空损坏的本地运行记录？"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>保留</Button>
              <Button
                variant="danger"
                onClick={() => {
                  store.reset();
                  setDialog(null);
                }}
              >
                确认清空记录缓存
              </Button>
            </>
          }
        >
          <p>
            仅清空新前端运行记录缓存；不会清空技能草稿或原项目。若原内容尚可读取，请先自行备份。
          </p>
        </Modal>
      )}
      {dialog === "other" && (
        <Modal title={other} onClose={() => setDialog(null)}>
          <p>
            该列表页尚未实现。本轮提供单次运行设置、模拟进度和结果证据，不跳转到旧服务。
          </p>
        </Modal>
      )}
    </AppShell>
  );
}
