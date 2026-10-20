import { useEffect, useRef, useState, type ChangeEvent } from "react";
import {
  ArrowLeftIcon,
  BellIcon,
  CheckCircleIcon,
  ClockIcon,
  DownloadSimpleIcon,
  FloppyDiskIcon,
  GearIcon,
  InfoIcon,
  MapPinIcon,
  ShareNetworkIcon,
  UploadSimpleIcon,
} from "@phosphor-icons/react";
import { AppShell } from "../AppShell";
import { Button, Modal } from "../ui";
import { RunMedia } from "../runs/RunMedia";
import { clone, type SkillDocument } from "../../data/document";
import { useVersions } from "../../data/useVersions";
import {
  draftFile,
  VERSION_FILE_LIMIT,
  versionFile,
  type SkillVersion,
} from "../../data/versions";
import { ruleSummary } from "../../data/ruleSummary";
import { validateIssues } from "../../data/validation";
import { downloadJson, readSettings } from "../../data/runs";
import { versionTimeSummary } from "../../data/versionSummary";
import { useHistoryLeaveGuard } from "../../data/navigation";

export function VersionExperience({
  draft,
  applied,
  revision,
  workspaceDirty,
  fixture,
  onCommit,
  onLoad,
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
  onLoad: (doc: SkillDocument, label: string) => void;
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
  const store = useVersions(draft, applied, fixture);
  const [selectedId, setSelectedId] = useState(() =>
    fixture === "12" ? `fixture-${draft.id}-v3` : "",
  );
  const selected =
    store.archive.versions.find((r) => r.id === selectedId) ??
    store.archive.versions[store.archive.versions.length - 1];
  const [name, setName] = useState(draft.name);
  const [note, setNote] = useState(
    fixture === "12" ? "调整区域人数阈值与证据配置" : "",
  );
  const baseline = useRef(
    JSON.stringify({
      name: draft.name,
      note: fixture === "12" ? "调整区域人数阈值与证据配置" : "",
    }),
  );
  const formDirty = JSON.stringify({ name, note }) !== baseline.current;
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [dialog, setDialog] = useState<"load" | "leave" | "other" | null>(null);
  const [other, setOther] = useState("");
  const [loadTarget, setLoadTarget] = useState<SkillVersion | null>(null);
  const [newest, setNewest] = useState<number | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const leaveAction = useRef<(doc?: SkillDocument) => void>(onBack);
  const nextNumber =
    Math.max(0, ...store.archive.versions.map((v) => v.number)) + 1;
  const proposed = { ...clone(draft), name: name.trim() };
  const proposedIssues = validateIssues(proposed);
  const detail = selected?.document;
  const detailSettings = detail && readSettings(detail);
  const sameAsRun = (doc: SkillDocument) =>
    revision > 0 && JSON.stringify(doc) === JSON.stringify(applied);
  useEffect(() => {
    mounted.current = true;
    const previous = document.title;
    document.title = "Vision Skill Forge · 完整技能与版本";
    if (!fixture)
      history.replaceState(
        history.state,
        "",
        `/skills/${encodeURIComponent(draft.id)}/versions`,
      );
    return () => {
      mounted.current = false;
      document.title = previous;
    };
  }, []);
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {
      if (formDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [formDirty]);
  const save = (): boolean => {
    if (!form.current?.reportValidity()) return false;
    setMessage("");
    try {
      const record = store.save(proposed, note);
      if (proposed.name !== draft.name) onCommit(proposed);
      setSelectedId(record.id);
      setNewest(record.number);
      setError("");
      baseline.current = JSON.stringify({ name, note });
      setMessage(
        `已保存完整技能 V${record.number} · 当前运行 R${revision} 未改变`,
      );
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  };
  const requestLeave = (action: (doc?: SkillDocument) => void) => {
    leaveAction.current = action;
    if (formDirty) setDialog("leave");
    else action();
  };
  const back = () => requestLeave(onBack);
  useHistoryLeaveGuard((proceed) => {
    if (!formDirty) return false;
    requestLeave((doc) =>
      onHistoryLeave ? onHistoryLeave(doc, proceed) : proceed(),
    );
    return true;
  });
  const requestLoad = (record: SkillVersion) => {
    setLoadTarget(clone(record));
    setDialog("load");
  };
  const load = (backup: boolean) => {
    if (!loadTarget) return;
    if (loadTarget.document.mediaRef !== draft.mediaRef) {
      setError(
        "此版本的素材引用与当前环境不同，尚不能打开该素材。版本已保留且可导出；不会用当前海报冒充它的素材。",
      );
      setDialog(null);
      return;
    }
    if (backup && !save()) {
      setDialog(null);
      return;
    }
    onLoad(clone(loadTarget.document), `V${loadTarget.number}`);
  };
  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget,
      file = input.files?.[0];
    if (!file) return;
    setMessage("");
    try {
      if (file.size > VERSION_FILE_LIMIT)
        throw new Error("文件超过 2 MB，未导入。素材文件不应嵌入技能 JSON。");
      const text = await file.text();
      if (!mounted.current) return;
      const result = store.importFile(text);
      setSelectedId(result.selected.id);
      setError("");
      setMessage(
        result.duplicate
          ? `V${result.selected.number} 已存在，未重复导入`
          : `已导入为 V${result.selected.number} · 尚未加载或应用`,
      );
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      input.value = "";
    }
  };
  const exportDraft = () => {
    try {
      downloadJson(
        draftFile(proposed, note),
        "vision-forge-complete-skill.json",
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const summaryRows = detail
    ? [
        {
          id: "logic",
          icon: ShareNetworkIcon,
          label: "条件与嵌套编排",
          value: `${detail.conditions.length} 项条件 · ${detail.branches.length} 个分支 · ${detail.groups.length} 个编排组`,
        },
        {
          id: "time",
          icon: ClockIcon,
          label: "时间要求",
          value: versionTimeSummary(detail),
        },
        {
          id: "outputs",
          icon: BellIcon,
          label: "业务输出",
          value: detail.outputs.map((o) => o.name).join("、"),
        },
        {
          id: "regions",
          icon: MapPinIcon,
          label: "场景标注",
          value:
            detail.regions
              .map((r) => `${r.name}${r.saved ? "" : "（待完成）"}`)
              .join("、") || "无需标注区域",
        },
        {
          id: "settings",
          icon: GearIcon,
          label: "运行配置",
          value: detailSettings
            ? `每 ${detailSettings.sampleIntervalSeconds} 秒采样；${detailSettings.tiles.enabled ? `${detailSettings.tiles.width}×${detailSettings.tiles.height} 切片` : "不切片"}；${{ instance: "实例融合", ios: "IoS", iou: "IoU" }[detailSettings.dedup.metric]} ${detailSettings.dedup.threshold}`
            : "未配置",
        },
      ]
    : [];
  return (
    <AppShell
      dirty={workspaceDirty}
      revision={revision}
      title={draft.name}
      onRun={() => {}}
      onApply={() => {}}
      onMenu={() => {}}
      onNavigate={(label) => {
        if (label === "技能库") requestLeave(onLibrary ?? onBack);
        else if (label === "模型接入" && onModels) requestLeave(onModels);
        else if (label === "能力管理" && onCapabilities)
          requestLeave(onCapabilities);
        else if (label === "运行记录" && onHistory) requestLeave(onHistory);
        else {
          setOther(label);
          setDialog("other");
        }
      }}
      actions={
        <>
          <Button icon={ArrowLeftIcon} onClick={back}>
            返回编辑
          </Button>
          <Button
            icon={FloppyDiskIcon}
            variant="primary"
            type="submit"
            form="save-complete-skill"
          >
            保存新版本
          </Button>
        </>
      }
    >
      <main className="versions-page">
        <div className="versions-location">
          <span>创建</span>
          <span>场景（可选）</span>
          <span>编排</span>
          <span>验证</span>
          <strong>完整技能与版本</strong>
        </div>
        <div className="versions-grid">
          <section className="panel version-history" aria-label="历史版本">
            <header>
              <h2>历史版本</h2>
              <Button
                icon={UploadSimpleIcon}
                onClick={() => fileInput.current?.click()}
              >
                导入版本
              </Button>
            </header>
            <input
              ref={fileInput}
              type="file"
              accept=".json,application/json"
              aria-label="导入完整技能文件"
              hidden
              onChange={importFile}
            />
            <div className="version-hint warning">
              <InfoIcon size={21} />
              <span>
                打开历史版本只替换草稿，不自动应用；当前修改可先保存为新版本。
              </span>
            </div>
            {store.warning && (
              <div className="version-hint warning" role="alert">
                {store.warning}
                <Button onClick={exportDraft}>导出当前草稿</Button>
              </div>
            )}
            {error && (
              <div className="version-hint warning" role="alert">
                <span>{error}</span>
                <Button onClick={exportDraft}>导出当前草稿</Button>
              </div>
            )}
            {message && (
              <div className="version-message" role="status">
                {message}
              </div>
            )}
            <div className="version-table-scroll">
              <table className="version-table">
                <thead>
                  <tr>
                    <th>版本</th>
                    <th>说明</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {[...store.archive.versions]
                    .sort((a, b) => b.number - a.number)
                    .map((r) => (
                      <tr
                        key={r.id}
                        className={
                          r.id === selected?.id ? "selected-version" : ""
                        }
                      >
                        <td>
                          <button
                            className="version-select"
                            onClick={() => setSelectedId(r.id)}
                            aria-label={`查看 V${r.number}`}
                            aria-pressed={selected?.id === r.id}
                          >
                            V{r.number}
                          </button>
                        </td>
                        <td>
                          <span>{r.note || "完整技能版本"}</span>
                        </td>
                        <td>
                          <strong
                            className={
                              sameAsRun(r.document) ? "version-running" : ""
                            }
                          >
                            {sameAsRun(r.document)
                              ? "与运行配置一致"
                              : "已保存版本"}
                          </strong>
                          <small>
                            {r.createdAt.slice(0, 10)}
                            {fixture ? " · 演示" : ""}
                          </small>
                        </td>
                        <td>
                          <div className="version-row-actions">
                            <Button
                              onClick={() => requestLoad(r)}
                              aria-label={`打开并编辑 V${r.number}`}
                            >
                              打开并编辑
                            </Button>
                            <Button
                              icon={DownloadSimpleIcon}
                              aria-label={`导出 V${r.number}`}
                              onClick={() =>
                                downloadJson(
                                  versionFile(r),
                                  `vision-forge-v${r.number}.json`,
                                )
                              }
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
              {!store.archive.versions.length && (
                <div className="version-empty">
                  <h3>还没有保存的版本</h3>
                  <p>保存当前完整草稿为 V1，或导入以前导出的技能文件。</p>
                  <Button
                    variant="primary"
                    type="submit"
                    form="save-complete-skill"
                  >
                    保存第一个版本
                  </Button>
                </div>
              )}
            </div>
            {detail && (
              <section
                className="version-summary"
                aria-label="所选版本内容摘要"
              >
                <h3>版本内容摘要（V{selected.number}）</h3>
                {summaryRows.map(({ id, icon: Icon, label, value }) => (
                  <div className="version-summary-row" key={id}>
                    <Icon size={25} />
                    <strong>{label}</strong>
                    <span>{value}</span>
                  </div>
                ))}
                <details>
                  <summary>查看所选版本的实际规则</summary>
                  <ul>
                    {ruleSummary(detail).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </details>
                {selected.importedFrom && (
                  <p className="field-help">
                    导入来源：V{selected.importedFrom.number}，本地编号为 V
                    {selected.number}。
                  </p>
                )}
              </section>
            )}
          </section>
          <section className="panel version-save" aria-label="保存完整技能">
            <form
              id="save-complete-skill"
              ref={form}
              onSubmit={(e) => {
                e.preventDefault();
                save();
              }}
            >
              <div className="version-save-body">
                <h2>保存完整技能</h2>
                <div className="version-hint">
                  <InfoIcon size={21} />
                  <span>
                    本次将创建 V{nextNumber}，不覆盖已有版本。
                    {newest ? `上次已保存 V${newest}。` : ""}
                  </span>
                </div>
                <label className="version-field">
                  技能名称
                  <input
                    aria-label="技能名称"
                    value={name}
                    maxLength={120}
                    required
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label className="version-field version-note">
                  版本说明
                  <div>
                    <textarea
                      aria-label="版本说明"
                      value={note}
                      rows={3}
                      maxLength={200}
                      onChange={(e) => setNote(e.target.value)}
                    />
                    <small>{note.length}/200</small>
                  </div>
                </label>
                <details className="version-advanced">
                  <summary>高级标识</summary>
                  <p>
                    技能身份：{draft.id} · Schema {draft.schemaVersion}
                  </p>
                  <p>V 是保存版本，R 是已应用运行修订，两者独立。</p>
                </details>
                <h3>待保存内容预览</h3>
                <div className="version-preview">
                  <div>
                    <RunMedia document={proposed} time={12} controls={false} />
                    <small>同源海报 · 仅保存素材引用</small>
                  </div>
                  <div className="version-preview-rules">
                    <strong>核心规则</strong>
                    {proposed.branches.map((b) => (
                      <div key={b.id}>
                        <ShareNetworkIcon size={22} />
                        <span>
                          {b.name}
                          <small>
                            {b.logic.members.length} 项条件 · {b.logic.operator}
                          </small>
                        </span>
                      </div>
                    ))}
                    <div>
                      <BellIcon size={23} />
                      <span>
                        {proposed.outputs.map((o) => o.name).join("、")}
                      </span>
                    </div>
                  </div>
                </div>
                <h3>内容完整性检查</h3>
                <div className="version-checks">
                  {[
                    "条件与嵌套编排",
                    "时间与有效状态",
                    "业务输出与触发",
                    "场景标注与素材引用",
                    "运行配置",
                    "自定义证据核对状态",
                  ].map((label) => (
                    <span key={label}>
                      <CheckCircleIcon size={21} weight="fill" />
                      {label}
                    </span>
                  ))}
                </div>
                <div className="version-hint compact">
                  <InfoIcon size={20} />
                  <span>
                    仅保存配置与素材引用，不含媒体文件、密钥或结果。运行 R
                    {revision} 不改变，加载后仍需校验并应用。
                    {proposedIssues.length
                      ? `尚有 ${proposedIssues.length} 项待处理。`
                      : ""}
                  </span>
                </div>
              </div>
              <footer>
                <Button onClick={back}>取消</Button>
                <button className="button primary" type="submit">
                  保存为 V{nextNumber}
                </button>
              </footer>
            </form>
          </section>
        </div>
      </main>
      {dialog === "load" && loadTarget && (
        <Modal
          title={`加载 V${loadTarget.number} 到草稿？`}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>取消</Button>
              <Button onClick={() => load(false)}>替换草稿并加载</Button>
              <Button variant="primary" onClick={() => load(true)}>
                先保存当前草稿再加载
              </Button>
            </>
          }
        >
          <p>
            将用 V{loadTarget.number} 的完整配置替换当前可编辑草稿
            {workspaceDirty || formDirty ? "，当前有未应用或未保存修改" : ""}。
          </p>
          <p>
            当前运行 R{revision}
            、已有任务及历史结果保持不变；不会从执行包重建或丢弃编排组。
          </p>
          <p>如果需要保留当前配置，请选择“先保存当前草稿再加载”。</p>
        </Modal>
      )}
      {dialog === "leave" && (
        <Modal
          title="版本说明尚未保存"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>继续编辑</Button>
              <Button onClick={() => leaveAction.current()}>
                放弃修改并返回
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  if (save()) leaveAction.current(proposed);
                }}
              >
                保存版本后返回
              </Button>
            </>
          }
        >
          <p>
            技能名称或版本说明还没有保存为版本。返回不会删除现有版本或应用当前草稿。
          </p>
        </Modal>
      )}
      {dialog === "other" && (
        <Modal title={other} onClose={() => setDialog(null)}>
          <p>该管理列表尚未实现。当前草稿、版本和运行记录未改变。</p>
          <Button onClick={() => setDialog(null)}>留在版本页</Button>
        </Modal>
      )}
    </AppShell>
  );
}
