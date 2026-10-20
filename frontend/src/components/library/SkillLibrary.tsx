import { useEffect, useRef, useState, type ChangeEvent } from "react";
import {
  ArrowRightIcon,
  DotsThreeVerticalIcon,
  CubeIcon,
  DownloadSimpleIcon,
  ImageIcon,
  ListIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  SquaresFourIcon,
  TrashIcon,
  UploadSimpleIcon,
  VideoCameraIcon,
} from "@phosphor-icons/react";
import { AppShell } from "../AppShell";
import { Button, IconButton, Modal } from "../ui";
import { SkillDetail } from "./SkillDetail";
import {
  entryStatus,
  entryThumbnail,
  libraryEntries,
  type LibraryEntry,
} from "../../data/libraryEntries";
import {
  createFromTemplate,
  deleteLocalSkill,
  installSkill,
} from "../../data/skillRepository";
import { draftFile, VERSION_FILE_LIMIT } from "../../data/versions";
import { downloadJson } from "../../data/runs";

export function SkillLibrary({
  fixture,
  startCreating,
  navigate,
}: {
  fixture: string;
  startCreating: boolean;
  navigate: (url: string) => void;
}) {
  const [rows, setRows] = useState<LibraryEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(() =>
    innerWidth < 1150 ? null : "regional-alert",
  );
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [layout, setLayout] = useState("list");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState<
    "create" | "conflict" | "delete" | "info" | null
  >(startCreating ? "create" : null);
  const [pendingRaw, setPendingRaw] = useState("");
  const [conflictDeleted, setConflictDeleted] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<LibraryEntry | null>(null);
  const [info, setInfo] = useState("");
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("regional-alert");
  const file = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const refresh = () => {
    try {
      setRows(libraryEntries(fixture));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    mounted.current = true;
    refresh();
    const title = document.title;
    document.title = "Vision Skill Forge · 我的视觉技能";
    const sync = () => refresh();
    window.addEventListener("storage", sync);
    window.addEventListener("vsf:library-changed", sync);
    return () => {
      mounted.current = false;
      document.title = title;
      window.removeEventListener("storage", sync);
      window.removeEventListener("vsf:library-changed", sync);
    };
  }, [fixture]);
  const filtered = rows.filter(
    (row) =>
      (tab === "all" ||
        row.origin === (tab === "mine" ? "local" : "reference")) &&
      `${row.name} ${row.instruction}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  const detail = filtered.find((row) => row.id === selected);
  const explain = (message: string) => {
    setInfo(message);
    setDialog("info");
  };
  const demoGuard = () => {
    if (!fixture) return false;
    explain(
      "这是隔离截图演示，不写入浏览器正常技能数据。请打开 /skills 后保存、导入或新建。",
    );
    return true;
  };
  const open = (entry: LibraryEntry, suffix = "editor?view=linked") => {
    if (!entry.data)
      return explain(
        entry.error ?? "此项仅有示例说明，尚未提供完整配置，不能进入编辑器。",
      );
    if (entry.data.draft.mediaRef !== "construction-poster")
      return explain(
        "素材尚未接入本前端。配置已保留，可导出；不会用当前施工图片冒充。",
      );
    navigate(
      `/skills/${encodeURIComponent(entry.id)}/${suffix}${fixture ? `${suffix.includes("?") ? "&" : "?"}fixture=${encodeURIComponent(fixture)}` : ""}`,
    );
  };
  const importRaw = (raw: string, copy = false) => {
    try {
      const result = installSkill(raw, copy);
      if (result.conflict) {
        setConflictDeleted(result.reason === "deleted");
        setPendingRaw(raw);
        setDialog("conflict");
        return;
      }
      refresh();
      setSelected(result.document.id);
      setTab("mine");
      setQuery("");
      setDialog(null);
      setPendingRaw("");
      setNotice("已导入完整技能到本地草稿，并保存 V1；尚未应用或启动任务。");
    } catch (e) {
      setError((e as Error).message);
      setDialog(null);
    }
  };
  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget,
      selectedFile = input.files?.[0];
    if (!selectedFile || demoGuard()) {
      input.value = "";
      return;
    }
    setNotice("");
    setError("");
    try {
      if (selectedFile.size > VERSION_FILE_LIMIT)
        throw new Error("文件超过 2 MB，未导入。");
      const raw = await selectedFile.text();
      if (mounted.current) importRaw(raw);
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      input.value = "";
    }
  };
  const exportEntry = (entry: LibraryEntry) => {
    try {
      if (!entry.data) throw new Error("此项没有可导出的完整配置。");
      downloadJson(
        draftFile(entry.data.draft),
        `${entry.id}-complete-skill.json`,
      );
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const runs = (entry: LibraryEntry) => {
    navigate(
      `/runs?skill=${encodeURIComponent(entry.id)}${fixture ? "&fixture=run-history" : ""}`,
    );
  };
  const doDelete = () => {
    if (!pendingDelete) return;
    try {
      deleteLocalSkill(pendingDelete.id);
      refresh();
      setSelected(null);
      setDialog(null);
      setNotice("已删除所选本地技能及其保存版本；历史运行记录未改变。");
    } catch (e) {
      setError((e as Error).message);
      setDialog(null);
    }
  };
  return (
    <AppShell
      dirty={false}
      revision={0}
      showRevision={false}
      title="我的视觉技能"
      onRun={() => {}}
      onApply={() => {}}
      onMenu={() => {}}
      onNavigate={(label) =>
        label === "技能库"
          ? undefined
          : label === "模型接入"
            ? navigate(`/settings/models${fixture ? "?fixture=models" : ""}`)
            : label === "能力管理"
              ? navigate(
                  `/settings/capabilities${fixture ? "?fixture=capabilities" : ""}`,
                )
              : label === "运行记录"
                ? navigate(`/runs${fixture ? "?fixture=run-history" : ""}`)
                : explain(`${label}总列表尚未实现，本页不会冒充其管理功能。`)
      }
      actions={<></>}
    >
      <main className={`library-page ${detail ? "with-detail" : ""}`}>
        <div className="library-main">
          <header className="library-heading">
            <div>
              <h1>我的视觉技能</h1>
              <p>管理和复用您的视觉技能，支持新建、导入和编辑。</p>
            </div>
            <div>
              <Button
                variant="primary"
                icon={PlusIcon}
                onClick={() => {
                  if (!demoGuard()) {
                    navigate("/skills/new");
                  }
                }}
              >
                新建技能
              </Button>
              <Button
                icon={UploadSimpleIcon}
                onClick={() => file.current?.click()}
              >
                导入技能
              </Button>
            </div>
          </header>
          <input
            type="file"
            ref={file}
            accept=".json,application/json"
            aria-label="导入完整技能到技能库"
            hidden
            onChange={importFile}
          />
          {error && (
            <div className="library-feedback warning" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="library-feedback" role="status">
              {notice}
            </div>
          )}
          <section className="panel library-catalog" aria-label="视觉技能列表">
            <div className="library-toolbar">
              <div role="tablist" aria-label="技能分类">
                {[
                  ["mine", "我的技能"],
                  ["reference", "预置示例"],
                  ["all", "全部"],
                ].map(([id, label]) => (
                  <button
                    role="tab"
                    aria-selected={tab === id}
                    key={id}
                    onClick={() => {
                      setTab(id);
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <label className="library-search">
                <MagnifyingGlassIcon size={21} />
                <input
                  aria-label="搜索技能名称或描述"
                  placeholder="搜索名称或描述"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
            </div>
            <div className="library-display library-display-toolbar">
              <span>{filtered.length} 项 · 示例说明不等于已生成技能</span>
              <div>
                <IconButton
                  label="列表视图"
                  icon={ListIcon}
                  aria-pressed={layout === "list"}
                  onClick={() => setLayout("list")}
                />
                <IconButton
                  label="卡片视图"
                  icon={SquaresFourIcon}
                  aria-pressed={layout === "cards"}
                  onClick={() => setLayout("cards")}
                />
              </div>
            </div>
            <div className={`library-entries ${layout}`}>
              {layout === "list" && (
                <div className="library-column-head" aria-hidden="true">
                  <span>技能名称</span>
                  <span>用途</span>
                  <span>媒体</span>
                  <span>版本状态</span>
                  <span>操作</span>
                </div>
              )}
              {filtered.map((entry) => (
                <article
                  className={`library-entry ${selected === entry.id ? "selected" : ""}`}
                  aria-label={`技能：${entry.name}`}
                  key={entry.id}
                >
                  <button
                    className="library-entry-name"
                    onClick={() => setSelected(entry.id)}
                    aria-pressed={selected === entry.id}
                  >
                    {entryThumbnail(entry) ? (
                      <img src={entryThumbnail(entry)} alt="" />
                    ) : (
                      <CubeIcon size={32} />
                    )}
                    <strong>{entry.name}</strong>
                  </button>
                  <p className="library-entry-description">
                    {entry.instruction}
                  </p>
                  <div className="library-entry-media">
                    {entry.data?.draft.mediaMode === "image" ||
                    ["furniture", "bridge-damage"].includes(entry.id) ? (
                      <ImageIcon size={24} />
                    ) : (
                      <VideoCameraIcon size={24} />
                    )}
                    <span>
                      {entry.data?.draft.mediaMode === "image" ||
                      ["furniture", "bridge-damage"].includes(entry.id)
                        ? "图片"
                        : "视频演示"}
                    </span>
                  </div>
                  <div className="library-entry-status">
                    {entry.data && entry.data.revision > 0 && (
                      <strong>R{entry.data.revision}</strong>
                    )}
                    <span
                      className={
                        entry.data
                          ? entryStatus(entry) === "已应用"
                            ? "applied"
                            : "draft"
                          : "reference"
                      }
                    >
                      {entryStatus(entry)}
                    </span>
                  </div>
                  <div className="library-entry-actions">
                    <Button
                      variant={
                        entry.data && selected === entry.id
                          ? "primary"
                          : "neutral"
                      }
                      onClick={() =>
                        entry.data ? open(entry) : setSelected(entry.id)
                      }
                    >
                      {entry.data ? "继续编辑" : "查看说明"}
                    </Button>
                    {entry.data && (
                      <details
                        className="library-row-menu"
                        onClick={(event) => {
                          if ((event.target as HTMLElement).closest("button"))
                            event.currentTarget.open = false;
                        }}
                      >
                        <summary aria-label={`更多操作：${entry.name}`}>
                          <DotsThreeVerticalIcon size={21} />
                        </summary>
                        <div>
                          <Button
                            icon={DownloadSimpleIcon}
                            onClick={() => exportEntry(entry)}
                          >
                            导出完整技能
                          </Button>
                          <Button onClick={() => open(entry, "versions")}>
                            查看保存版本
                          </Button>
                          <Button
                            variant="danger"
                            icon={TrashIcon}
                            onClick={() => {
                              if (!demoGuard()) {
                                setPendingDelete(entry);
                                setDialog("delete");
                              }
                            }}
                          >
                            删除本地技能
                          </Button>
                        </div>
                      </details>
                    )}
                  </div>
                </article>
              ))}
              {!filtered.length && (
                <div className="library-empty">
                  <CubeIcon size={36} />
                  <h2>{query ? "没有匹配的技能" : "这里还没有技能"}</h2>
                  <p>
                    {query
                      ? "请尝试其它关键词，或清除搜索和分类筛选。"
                      : "从模板新建，或导入完整技能 JSON 后继续编辑。"}
                  </p>
                  <Button
                    onClick={() => {
                      setQuery("");
                      setTab("all");
                    }}
                  >
                    清除筛选
                  </Button>
                  <Button onClick={() => file.current?.click()}>
                    导入完整技能
                  </Button>
                </div>
              )}
            </div>
            <footer>
              <Button
                variant="subtle"
                icon={SquaresFourIcon}
                onClick={() => {
                  setTab("reference");
                  setQuery("");
                }}
              >
                浏览 {rows.filter((r) => r.origin === "reference").length}{" "}
                项示例说明 <ArrowRightIcon />
              </Button>
            </footer>
          </section>
        </div>
        {detail && (
          <SkillDetail
            entry={detail}
            onClose={() => setSelected(null)}
            onEdit={() => open(detail)}
            onRuns={() => runs(detail)}
          />
        )}
      </main>
      {dialog === "info" && (
        <Modal
          title="功能说明"
          onClose={() => setDialog(null)}
          footer={<Button onClick={() => setDialog(null)}>知道了</Button>}
        >
          <p>{info}</p>
        </Modal>
      )}
      {dialog === "create" && (
        <Modal
          title="从完整模板新建"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>取消</Button>
              <Button variant="primary" type="submit" form="library-create">
                创建并编辑
              </Button>
            </>
          }
        >
          <form
            id="library-create"
            className="library-create"
            onSubmit={(e) => {
              e.preventDefault();
              if (demoGuard()) return;
              try {
                const result = createFromTemplate(template, name);
                if (!result.conflict)
                  navigate(
                    `/skills/${result.document.id}/editor?view=${template === "sequence-demo" ? "orchestration" : "linked"}`,
                  );
              } catch (error) {
                setError((error as Error).message);
                setDialog(null);
              }
            }}
          >
            <p>
              复制明确的演示模板为独立技能，不调用
              LLM；请按实际任务修改配置后校验应用。
            </p>
            <label>
              技能名称
              <input
                aria-label="新技能名称"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={120}
              />
            </label>
            <label>
              完整模板
              <select
                aria-label="完整技能模板"
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
              >
                <option value="regional-alert">区域联合告警</option>
                <option value="sequence-demo">时序组合示例</option>
              </select>
            </label>
          </form>
        </Modal>
      )}
      {dialog === "conflict" && (
        <Modal
          title={conflictDeleted ? "该技能身份已删除" : "该技能已存在"}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>取消</Button>
              <Button
                variant="primary"
                onClick={() => importRaw(pendingRaw, true)}
              >
                另存为独立副本
              </Button>
            </>
          }
        >
          <p>
            {conflictDeleted
              ? "这个身份已删除并留有防误恢复标记。导入备份将创建新身份，不会重写旧运行记录。"
              : "导入文件与现有技能身份相同。现有草稿、运行版本、保存版本及结果不会被覆盖。"}
            副本使用新身份，内部编排结构保持不变。
          </p>
        </Modal>
      )}
      {dialog === "delete" && pendingDelete && (
        <Modal
          title={`删除“${pendingDelete.name}”？`}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>取消</Button>
              <Button onClick={() => exportEntry(pendingDelete)}>
                先导出配置备份
              </Button>
              <Button variant="danger" onClick={doDelete}>
                确认删除本地技能
              </Button>
            </>
          }
        >
          <p>
            仅删除这个技能的本地草稿、运行配置和保存版本，历史运行记录及其快照保留。存在未结束任务时不能删除。
          </p>
          <p>其它技能不受影响；删除后可通过导入备份为新副本恢复。</p>
        </Modal>
      )}
    </AppShell>
  );
}
