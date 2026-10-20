import { useEffect, useRef, useState } from "react";
import {
  PlusIcon,
  MagnifyingGlassIcon,
  DotsThreeIcon,
  DownloadSimpleIcon,
} from "@phosphor-icons/react";
import { AppShell } from "../AppShell";
import { Button, IconButton, Modal } from "../ui";
import { CapabilityDetail, capabilityIcon } from "./CapabilityDetail";
import {
  CAPABILITY_KEY,
  catalog,
  capabilityClosure,
  enabled,
  exampleCapability,
  kindNames,
  parseManifest,
  readCapabilities,
  removeCapability,
  seedCapabilities,
  toggleCapability,
  writeCapabilities,
  type CapabilityKind,
  type CapabilityManifest,
  type CapabilityRegistry,
} from "../../data/capabilities";
import {
  capabilityUsage,
  type CapabilityUse,
} from "../../data/capabilityUsage";
import { useHistoryLeaveGuard } from "../../data/navigation";
import { downloadJson } from "../../data/runs";

export function CapabilityManagement({
  fixture,
  navigate,
}: {
  fixture: string;
  navigate: (url: string) => void;
}) {
  const [initial] = useState(() => {
    try {
      return {
        ...(fixture
          ? { registry: seedCapabilities(), raw: null }
          : readCapabilities()),
        error: "",
      };
    } catch (e) {
      return {
        registry: {
          schemaVersion: 1,
          states: {},
          custom: [],
        } as CapabilityRegistry,
        raw: null,
        error: (e as Error).message,
      };
    }
  });
  const [registry, setRegistry] = useState(initial.registry),
    raw = useRef(initial.raw);
  const [blocked, setBlocked] = useState(!!initial.error),
    [error, setError] = useState(initial.error),
    [notice, setNotice] = useState("");
  const [filter, setFilter] = useState<CapabilityKind | "all">("all"),
    [search, setSearch] = useState(""),
    [supporting, setSupporting] = useState(false),
    [selected, setSelected] = useState("color-review");
  const [dialog, setDialog] = useState<
      "import" | "disable" | "delete" | "leave" | "info" | null
    >(null),
    [actionId, setActionId] = useState("");
  const [candidate, setCandidate] = useState<CapabilityManifest | null>(null),
    [fileError, setFileError] = useState(""),
    [info, setInfo] = useState("");
  const [menu, setMenu] = useState(""),
    [menuPosition, setMenuPosition] = useState({ left: 0, top: 0 });
  const [, refresh] = useState(0),
    pending = useRef<(() => void) | null>(null),
    fileGeneration = useRef(0);
  const request = (action: () => void) => {
    if (candidate) {
      pending.current = action;
      setDialog("leave");
    } else action();
  };
  useHistoryLeaveGuard((proceed) => {
    if (!candidate) return false;
    request(proceed);
    return true;
  });
  useEffect(() => {
    const before = (e: BeforeUnloadEvent) => {
      if (candidate) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", before);
    return () => window.removeEventListener("beforeunload", before);
  }, [candidate]);
  useEffect(() => {
    const previous = document.title;
    document.title = "Vision Skill Forge · 能力管理";
    return () => {
      document.title = previous;
      fileGeneration.current++;
    };
  }, []);
  const reload = () => {
    if (fixture) return;
    try {
      const loaded = readCapabilities();
      raw.current = loaded.raw;
      setRegistry(loaded.registry);
      setBlocked(false);
      setError("");
      setCandidate(null);
      fileGeneration.current++;
    } catch (e) {
      setBlocked(true);
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    const sync = (e: StorageEvent) => {
      if (fixture) return;
      if (e.key === CAPABILITY_KEY || e.key === null) {
        if (candidate || dialog === "disable" || dialog === "delete") {
          setBlocked(true);
          setError(
            "其它页面已修改能力配置。当前内容仍保留，请重新载入后再操作。",
          );
        } else reload();
      }
      refresh((n) => n + 1);
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, [fixture, candidate, dialog]);
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu("");
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("click", close);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", key);
    };
  }, [menu]);
  const persist = (next: CapabilityRegistry) => {
    if (blocked)
      throw new Error("当前缓存不可写，请先重新载入；不会覆盖原内容。");
    if (!fixture) {
      try {
        raw.current = writeCapabilities(next, raw.current);
      } catch (e) {
        if (localStorage.getItem(CAPABILITY_KEY) !== raw.current)
          setBlocked(true);
        throw e;
      }
    }
    setRegistry(next);
    setError("");
    setNotice(
      fixture
        ? "隔离演示：仅更新本页内存，不写入正常数据。"
        : "能力配置已保存到本浏览器；未改写技能、运行版本或历史结果。",
    );
  };
  const audit = (id: string) => capabilityUsage(id, registry, fixture);
  let uses: CapabilityUse[] = [],
    auditError = "";
  try {
    uses = audit(selected);
  } catch (e) {
    auditError = `引用检查未完成：${(e as Error).message}`;
  }
  const all = catalog(registry),
    visible = all.filter(
      (c) =>
        (supporting || !c.supporting) &&
        (filter === "all" || c.kind === filter) &&
        `${c.name} ${c.description} ${c.id}`
          .toLowerCase()
          .includes(search.toLowerCase().trim()),
    );
  const item = visible.find((c) => c.id === selected);
  const choose = (id: string) => {
    setSupporting(true);
    setFilter("all");
    setSearch("");
    setSelected(id);
  };
  const toggle = (id: string) => {
    setMenu("");
    try {
      if (enabled(registry, id)) {
        audit(id);
        setActionId(id);
        setDialog("disable");
      } else persist(toggleCapability(registry, id, true));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const remove = (id: string) => {
    setMenu("");
    setActionId(id);
    setDialog("delete");
  };
  let affected: CapabilityUse[] = [],
    actionError = "";
  try {
    if (actionId) affected = audit(actionId);
  } catch (e) {
    actionError = `无法安全检查引用：${(e as Error).message}`;
  }
  const dependents = all.filter(
    (c) =>
      c.id !== actionId &&
      capabilityClosure(registry, c.uses).includes(actionId),
  );
  const suffix = fixture ? "?fixture=capabilities" : "";
  return (
    <AppShell
      className="capabilities-shell"
      title="能力管理"
      dirty={false}
      revision={0}
      showRevision={false}
      activeNavigation="能力管理"
      onApply={() => {}}
      onRun={() => {}}
      onMenu={() => {}}
      onNavigate={(label) => {
        if (label === "能力管理") return;
        if (label === "技能库")
          request(() => navigate(`/skills${fixture ? "?fixture=01" : ""}`));
        else if (label === "模型接入")
          request(() =>
            navigate(`/settings/models${fixture ? "?fixture=models" : ""}`),
          );
        else if (label === "运行记录")
          request(() =>
            navigate(`/runs${fixture ? "?fixture=run-history" : ""}`),
          );
        else {
          setInfo("运行总列表尚未实现；请在技能的测试运行中查看已有任务。");
          setDialog("info");
        }
      }}
      actions={
        <Button
          icon={PlusIcon}
          variant="primary"
          disabled={blocked}
          onClick={() => {
            setFileError("");
            setCandidate(null);
            setDialog("import");
          }}
        >
          安装自定义能力
        </Button>
      }
    >
      <main className="capabilities-page">
        <header className="capabilities-heading">
          <h1>能力管理</h1>
          <p>启用后可供自然语言编排使用，停用前检查已有技能依赖。</p>
        </header>
        <div className="capabilities-tools">
          <div className="panel" role="tablist" aria-label="能力类型">
            {(["all", "business", "execution", "template"] as const).map(
              (k) => (
                <button
                  key={k}
                  role="tab"
                  aria-selected={filter === k}
                  onClick={() => setFilter(k)}
                >
                  {k === "all" ? "全部" : kindNames[k]}
                </button>
              ),
            )}
          </div>
          <label className="panel capability-search">
            <MagnifyingGlassIcon size={23} />
            <input
              aria-label="搜索能力"
              placeholder="名称或用途"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>
        <div className="capabilities-columns">
          <section className="panel capability-list" aria-label="能力列表">
            <div className="capability-table-scroll">
              <table>
                <thead>
                  <tr>
                    {["能力名称", "类型", "来源", "状态", "操作"].map((t) => (
                      <th key={t}>{t}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visible.map((c) => {
                    const Icon = capabilityIcon(c.id);
                    return (
                      <tr
                        key={c.id}
                        className={selected === c.id ? "selected" : ""}
                      >
                        <td>
                          <button
                            className="capability-name"
                            onClick={() => setSelected(c.id)}
                          >
                            <Icon size={29} />
                            <strong>{c.name}</strong>
                          </button>
                        </td>
                        <td>
                          <span className={`capability-kind ${c.kind}`}>
                            {kindNames[c.kind]}
                          </span>
                        </td>
                        <td>{c.builtin ? "内置" : "用户自定义"}</td>
                        <td>
                          <button
                            className="capability-switch"
                            role="switch"
                            aria-label={`${c.name}启用状态`}
                            aria-checked={enabled(registry, c.id)}
                            disabled={blocked}
                            onClick={() => toggle(c.id)}
                          >
                            <span />
                          </button>
                        </td>
                        <td>
                          <IconButton
                            icon={DotsThreeIcon}
                            label={`更多操作：${c.name}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              const box =
                                e.currentTarget.getBoundingClientRect();
                              setMenuPosition({
                                left: Math.min(box.left, innerWidth - 215),
                                top: Math.min(box.bottom, innerHeight - 160),
                              });
                              setMenu(menu === c.id ? "" : c.id);
                            }}
                          />
                          {menu === c.id && (
                            <div
                              className="capability-menu"
                              style={menuPosition}
                            >
                              <Button onClick={() => setSelected(c.id)}>
                                查看详情
                              </Button>
                              <Button
                                onClick={() => {
                                  const {
                                    builtin,
                                    supporting: support,
                                    ...manifest
                                  } = c;
                                  downloadJson(
                                    manifest,
                                    `${c.id}-manifest.json`,
                                  );
                                }}
                              >
                                导出清单
                              </Button>
                              <Button
                                variant="danger"
                                disabled={c.builtin || blocked}
                                onClick={() => remove(c.id)}
                              >
                                {c.builtin ? "内置不可删除" : "删除自定义能力"}
                              </Button>
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {!visible.length && (
              <p className="capability-empty-inline">
                没有符合筛选条件的能力。
              </p>
            )}
            <label className="capability-supporting">
              <input
                type="checkbox"
                checked={supporting}
                onChange={(e) => setSupporting(e.target.checked)}
              />
              显示基础依赖能力
            </label>
            {error && (
              <div className="capability-error" role="alert">
                {error}
                {blocked && (
                  <Button onClick={() => request(reload)}>重新载入配置</Button>
                )}
              </div>
            )}
            {notice && (
              <p className="capability-notice" role="status">
                {notice}
              </p>
            )}
          </section>
          {item ? (
            <CapabilityDetail
              item={item}
              registry={registry}
              uses={uses}
              auditError={auditError}
              select={choose}
              openSkill={(id) =>
                request(() =>
                  navigate(`/skills/${encodeURIComponent(id)}/editor${suffix}`),
                )
              }
              remove={() => remove(item.id)}
            />
          ) : (
            <section className="panel capability-detail" aria-label="能力详情">
              <p className="capability-empty-inline">
                请从当前列表选择能力查看详情。
              </p>
            </section>
          )}
        </div>
      </main>
      {dialog === "import" && (
        <Modal
          title="安装自定义能力清单"
          onClose={() => {
            fileGeneration.current++;
            setDialog(null);
            setCandidate(null);
          }}
          footer={
            <>
              <Button
                icon={DownloadSimpleIcon}
                onClick={() =>
                  downloadJson(
                    {
                      ...exampleCapability,
                      id: "my-region-patrol",
                      name: "我的区域巡检",
                    },
                    "capability-manifest-example.json",
                  )
                }
              >
                下载清单示例
              </Button>
              <Button
                variant="primary"
                disabled={!candidate || blocked}
                onClick={() => {
                  try {
                    if (!candidate) return;
                    const checked = parseManifest(
                      JSON.stringify(candidate),
                      registry,
                    );
                    persist({
                      ...registry,
                      custom: [...registry.custom, checked],
                      states: { ...registry.states, [checked.id]: false },
                    });
                    choose(checked.id);
                    setCandidate(null);
                    setDialog(null);
                  } catch (e) {
                    setFileError((e as Error).message);
                  }
                }}
              >
                确认安装（默认停用）
              </Button>
            </>
          }
        >
          <p>
            仅接受128 KB以内的 JSON
            声明清单。不会执行代码、连接模型或自动启用；自定义编译器／执行器尚未接入。
          </p>
          <label className="capability-file">
            选择清单文件
            <input
              type="file"
              accept=".json,application/json"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                const token = ++fileGeneration.current;
                setCandidate(null);
                setFileError("");
                if (!file) return;
                try {
                  if (file.size > 128 * 1024)
                    throw new Error("清单超过128 KB，未安装。");
                  const text = await file.text();
                  if (token !== fileGeneration.current) return;
                  setCandidate(parseManifest(text, registry));
                } catch (e) {
                  if (token === fileGeneration.current)
                    setFileError((e as Error).message);
                }
              }}
            />
          </label>
          {candidate && (
            <div className="capability-import-preview">
              <h3>{candidate.name}</h3>
              <p>
                {kindNames[candidate.kind]} · {candidate.id}
              </p>
              <p>{candidate.description}</p>
              <p>
                依赖：
                {candidate.uses
                  .map((id) => all.find((c) => c.id === id)?.name ?? id)
                  .join("、") || "无"}
              </p>
              <p>安装后：停用 · 仅清单，尚不可执行</p>
            </div>
          )}
          {fileError && (
            <p className="capability-error" role="alert">
              {fileError}
            </p>
          )}
          {blocked && (
            <p className="capability-error" role="alert">
              {error}
            </p>
          )}
        </Modal>
      )}
      {(dialog === "disable" || dialog === "delete") && (
        <Modal
          title={dialog === "disable" ? "停用这个能力？" : "删除自定义能力？"}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>取消</Button>
              <Button
                variant="danger"
                disabled={
                  blocked ||
                  !!actionError ||
                  (dialog === "delete" &&
                    (!!affected.length || !!dependents.length))
                }
                onClick={() => {
                  try {
                    const currentUses = audit(actionId);
                    persist(
                      dialog === "disable"
                        ? toggleCapability(registry, actionId, false)
                        : removeCapability(
                            registry,
                            actionId,
                            currentUses.map((u) => u.name),
                          ),
                    );
                    setDialog(null);
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                {dialog === "disable" ? "确认停用" : "确认删除"}
              </Button>
            </>
          }
        >
          <p>
            {dialog === "disable"
              ? "依赖此能力的新应用、运行和继续运行将被阻止。不会自动替换能力，不改写已有草稿、运行版本或历史结果。"
              : "只删除此用户自定义清单；有技能、保存版本或其它能力引用时不可删除。内置能力不可删除。"}
          </p>
          <h3>受影响的技能</h3>
          {affected.length ? (
            <ul>
              {affected.map((u) => (
                <li key={u.id}>
                  {u.name}：{u.contexts.join("、")}
                </li>
              ))}
            </ul>
          ) : (
            <p>暂无技能引用</p>
          )}
          {dependents.length > 0 && (
            <>
              <h3>依赖此能力的其它能力</h3>
              <ul>
                {dependents.map((c) => (
                  <li key={c.id}>
                    {c.name}
                    {enabled(registry, c.id) ? "（已启用）" : "（已停用）"}
                  </li>
                ))}
              </ul>
            </>
          )}
          {(actionError || error) && (
            <p className="capability-error" role="alert">
              {actionError || error}
            </p>
          )}
        </Modal>
      )}
      {dialog === "leave" && (
        <Modal
          title="有尚未安装的能力清单"
          onClose={() => setDialog("import")}
          footer={
            <>
              <Button onClick={() => setDialog("import")}>返回安装预览</Button>
              <Button
                onClick={() => {
                  fileGeneration.current++;
                  setCandidate(null);
                  setDialog(null);
                  pending.current?.();
                }}
              >
                放弃清单并继续
              </Button>
            </>
          }
        >
          <p>当前只读取了文件，还没有安装。请选择返回确认安装或放弃预览。</p>
        </Modal>
      )}
      {dialog === "info" && (
        <Modal
          title="前端演示说明"
          onClose={() => setDialog(null)}
          footer={<Button onClick={() => setDialog(null)}>知道了</Button>}
        >
          <p>{info}</p>
        </Modal>
      )}
    </AppShell>
  );
}
