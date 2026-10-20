import { useEffect, useRef, useState } from "react";
import {
  CaretRightIcon,
  DotsThreeVerticalIcon,
  InfoIcon,
  PlusIcon,
} from "@phosphor-icons/react";
import { AppShell } from "../AppShell";
import { ModelConfigForm } from "./ModelConfigForm";
import { Button, IconButton, Modal } from "../ui";
import { useHistoryLeaveGuard } from "../../data/navigation";
import {
  adapterNames,
  chooseModel,
  emptyModel,
  MODEL_STORAGE_KEY,
  outputNames,
  readModels,
  roleNames,
  saveModel,
  seedModels,
  setModelEnabled,
  validateModel,
  writeModels,
  type ModelConnection,
  type ModelRegistry,
  type ModelRole,
} from "../../data/modelConnections";

export function ModelConnections({
  fixture,
  navigate,
}: {
  fixture: string;
  navigate: (path: string) => void;
}) {
  const [initial] = useState(() => {
    try {
      return {
        ...(fixture ? { registry: seedModels(true), raw: null } : readModels()),
        error: "",
      };
    } catch (e) {
      return {
        registry: {
          schemaVersion: 1,
          models: [],
          selected: {},
        } as ModelRegistry,
        raw: null,
        error: (e as Error).message,
      };
    }
  });
  const [registry, setRegistry] = useState(initial.registry),
    [role, setRole] = useState<ModelRole>("vision");
  const [form, setForm] = useState<ModelConnection | null>(() =>
    structuredClone(
      initial.registry.models.find((m) => m.id === "visual-demo") ?? null,
    ),
  );
  const baseline = useRef(JSON.stringify(form)),
    raw = useRef<string | null>(initial.raw);
  const [blocked, setBlocked] = useState(!!initial.error),
    [error, setError] = useState(initial.error),
    [notice, setNotice] = useState("");
  const [info, setInfo] = useState(""),
    [menu, setMenu] = useState("");
  const [menuPosition, setMenuPosition] = useState({ left: 0, top: 0 });
  const pending = useRef<((snapshot: ModelRegistry) => void) | null>(null),
    [dialog, setDialog] = useState<"leave" | "disable" | null>(null);
  const disableId = useRef("");
  const dirty = JSON.stringify(form) !== baseline.current;
  const setEditor = (model: ModelConnection | null) => {
    const next = structuredClone(model);
    baseline.current = JSON.stringify(next);
    setForm(next);
    if (!blocked) setError("");
    setNotice("");
    setMenu("");
  };
  const update = (patch: Partial<ModelConnection>) => {
    setForm((v) => (v ? { ...v, ...patch } : v));
    setError("");
    setNotice("");
  };
  const request = (action: (snapshot: ModelRegistry) => void) => {
    if (dirty) {
      pending.current = action;
      setDialog("leave");
    } else action(registry);
  };
  useHistoryLeaveGuard((proceed) => {
    if (!dirty) return false;
    pending.current = proceed;
    setDialog("leave");
    return true;
  });
  useEffect(() => {
    const title = document.title;
    document.title = "Vision Skill Forge · 模型接入";
    return () => {
      document.title = title;
    };
  }, []);
  useEffect(() => {
    const before = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", before);
    return () => window.removeEventListener("beforeunload", before);
  }, [dirty]);
  const reload = () => {
    if (fixture) return;
    try {
      const loaded = readModels();
      raw.current = loaded.raw;
      setRegistry(loaded.registry);
      setBlocked(false);
      setEditor(
        loaded.registry.models.find((m) => m.id === form?.id) ??
          loaded.registry.models.find((m) => m.role === role) ??
          null,
      );
      setError("");
    } catch (e) {
      setBlocked(true);
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    const storage = (event: StorageEvent) => {
      if (fixture || (event.key !== null && event.key !== MODEL_STORAGE_KEY))
        return;
      if (dirty) {
        setBlocked(true);
        setError("配置已在其它页面修改。当前输入仍保留，请重新载入后再编辑。");
      } else reload();
    };
    window.addEventListener("storage", storage);
    return () => window.removeEventListener("storage", storage);
  }, [dirty, fixture, form?.id, role]);
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu("");
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("click", close);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", key);
    };
  }, [menu]);
  const persist = (next: ModelRegistry) => {
    if (blocked)
      throw new Error("当前配置不可保存，请先重新载入；不会覆盖原内容。");
    if (!fixture) raw.current = writeModels(next, raw.current);
    setRegistry(next);
  };
  const save = () => {
    if (!form) return null;
    try {
      const next = saveModel(registry, form);
      persist(next);
      const saved = next.models.find((m) => m.id === form.id)!;
      baseline.current = JSON.stringify(saved);
      setForm(structuredClone(saved));
      setNotice(
        fixture
          ? "隔离演示：配置已保存到本页内存，不写入正常数据；未连接模型。"
          : "配置已保存，仅保存在本浏览器；未连接模型，也未修改技能或运行快照。",
      );
      setError("");
      return next;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  };
  const selectRole = (next: ModelRole) =>
    request((snapshot) => {
      setRole(next);
      setEditor(snapshot.models.find((m) => m.role === next) ?? null);
    });
  const action = (
    id: string,
    mode: "enable" | "disable" | "choose" | "clear",
  ) =>
    request((snapshot) => {
      setMenu("");
      if (mode === "disable" && Object.values(snapshot.selected).includes(id)) {
        disableId.current = id;
        setDialog("disable");
        return;
      }
      try {
        const next =
          mode === "choose"
            ? chooseModel(snapshot, id)
            : mode === "clear"
              ? {
                  ...snapshot,
                  selected: Object.fromEntries(
                    Object.entries(snapshot.selected).filter(
                      ([, value]) => value !== id,
                    ),
                  ),
                }
              : setModelEnabled(snapshot, id, mode === "enable");
        persist(next);
        const changed = next.models.find((m) => m.id === form?.id);
        if (changed) {
          baseline.current = JSON.stringify(changed);
          setForm(structuredClone(changed));
        }
        setNotice(
          mode === "choose"
            ? "已保存待接入选择，连接尚未验证；不会切换现有运行任务。"
            : "模型配置状态已更新；不会自动选择替代模型。未连接后端。",
        );
        setError("");
      } catch (e) {
        setError((e as Error).message);
      }
    });
  const add = () => request(() => setEditor(emptyModel(role)));
  const currentName = (r: ModelRole) =>
    registry.models.find((m) => m.id === registry.selected[r])?.name ??
    "未选择";
  return (
    <AppShell
      className="models-shell"
      title="统一接入配置"
      dirty={false}
      revision={0}
      showRevision={false}
      activeNavigation="模型接入"
      onApply={() => {}}
      onRun={() => {}}
      onMenu={() => {}}
      onNavigate={(label) =>
        label === "技能库"
          ? request(() => navigate(`/skills${fixture ? "?fixture=01" : ""}`))
          : label === "模型接入"
            ? undefined
            : label === "能力管理"
              ? request(() =>
                  navigate(
                    `/settings/capabilities${fixture ? "?fixture=capabilities" : ""}`,
                  ),
                )
              : label === "运行记录"
                ? request(() =>
                    navigate(`/runs${fixture ? "?fixture=run-history" : ""}`),
                  )
                : setInfo(`${label}总列表尚未实现；本页不执行模型或插件。`)
      }
      actions={
        <Button
          variant="primary"
          icon={PlusIcon}
          disabled={blocked}
          onClick={add}
        >
          添加模型
        </Button>
      }
    >
      <main className="models-page">
        <header className="models-heading">
          <h1>模型接入</h1>
          <p>统一接入编排模型与视觉模型，按需手动更换。</p>
        </header>
        <div className="models-columns">
          <section className="panel models-list" aria-label="模型列表">
            <div role="tablist" aria-label="模型用途">
              {(["planner", "vision"] as const).map((r) => (
                <button
                  role="tab"
                  key={r}
                  aria-selected={role === r}
                  onClick={() => selectRole(r)}
                >
                  {roleNames[r]}
                </button>
              ))}
            </div>
            <div className="models-table-scroll">
              <table>
                <thead>
                  <tr>
                    {["名称", "接入方式", "输出能力", "配置状态", "操作"].map(
                      (t) => (
                        <th key={t}>{t}</th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {registry.models
                    .filter((m) => m.role === role)
                    .map((model) => (
                      <tr
                        key={model.id}
                        className={form?.id === model.id ? "selected" : ""}
                      >
                        <td>
                          <strong>{model.name}</strong>
                        </td>
                        <td>{adapterNames[model.adapter]}</td>
                        <td>{outputNames[model.output]}</td>
                        <td>
                          <span
                            className={`model-status ${registry.selected[role] === model.id ? "chosen" : ""}`}
                          >
                            {registry.selected[role] === model.id
                              ? "已选择 · 未连接"
                              : model.enabled
                                ? "已启用 · 未选择"
                                : "未启用"}
                          </span>
                        </td>
                        <td>
                          <div className="model-row-actions">
                            <button
                              onClick={() =>
                                request((snapshot) =>
                                  setEditor(
                                    snapshot.models.find(
                                      (m) => m.id === model.id,
                                    ) ?? null,
                                  ),
                                )
                              }
                              aria-label={`配置${model.name}`}
                            >
                              配置
                            </button>
                            <IconButton
                              label={`更多操作：${model.name}`}
                              icon={DotsThreeVerticalIcon}
                              onClick={(e) => {
                                e.stopPropagation();
                                const box =
                                  e.currentTarget.getBoundingClientRect();
                                setMenuPosition({
                                  left: Math.min(box.left, innerWidth - 220),
                                  top: Math.min(box.bottom, innerHeight - 120),
                                });
                                setMenu((v) =>
                                  v === model.id ? "" : model.id,
                                );
                              }}
                            />
                            {menu === model.id && (
                              <div
                                className="model-row-menu"
                                style={menuPosition}
                              >
                                <Button
                                  onClick={() =>
                                    action(
                                      model.id,
                                      model.enabled ? "disable" : "enable",
                                    )
                                  }
                                >
                                  {model.enabled ? "停用配置" : "启用配置"}
                                </Button>
                                {registry.selected[role] === model.id ? (
                                  <Button
                                    onClick={() => action(model.id, "clear")}
                                  >
                                    取消选择
                                  </Button>
                                ) : (
                                  <Button
                                    disabled={!model.enabled}
                                    onClick={() => action(model.id, "choose")}
                                  >
                                    选为待接入模型
                                  </Button>
                                )}
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            {blocked && (
              <div className="models-blocked">
                <p role="alert">{error}</p>
                <Button onClick={() => request(reload)}>重新载入配置</Button>
              </div>
            )}
            {!registry.models.some((m) => m.role === role) && !blocked && (
              <p className="models-empty">尚未添加此用途的模型。</p>
            )}
            <div className="models-selection-info">
              <InfoIcon size={23} />
              <span>
                {roleNames[role === "vision" ? "planner" : "vision"]}：
                {currentName(role === "vision" ? "planner" : "vision")}
              </span>
              <button
                onClick={() =>
                  selectRole(role === "vision" ? "planner" : "vision")
                }
              >
                去配置
                <CaretRightIcon size={17} />
              </button>
            </div>
          </section>
          <section className="panel models-editor" aria-label="模型配置">
            <h2>配置{roleNames[role]}</h2>
            <p className="models-editor-subtitle">
              {form ? (
                <>
                  为 <strong>{form.name || "新模型"}</strong>{" "}
                  配置连接信息与能力声明。
                </>
              ) : (
                "选择或添加模型后编辑配置。"
              )}
            </p>
            {form && (
              <ModelConfigForm
                form={form}
                role={role}
                blocked={blocked}
                update={update}
                onSave={() => {
                  save();
                }}
                onCheck={() => {
                  const errors = validateModel(form, registry.models);
                  if (errors.length) {
                    setError(errors.join(" "));
                    setNotice("");
                  } else {
                    setError("");
                    setNotice(
                      "本地配置检查通过；未发送请求，连接未验证、输出能力未实测。",
                    );
                  }
                }}
              />
            )}
            {!blocked && error && (
              <p className="model-error" role="alert">
                {error}
              </p>
            )}
            {notice && (
              <p className="model-notice" role="status">
                {notice}
              </p>
            )}
          </section>
        </div>
      </main>
      {info && (
        <Modal
          title="前端演示说明"
          onClose={() => setInfo("")}
          footer={<Button onClick={() => setInfo("")}>知道了</Button>}
        >
          <p>{info}</p>
        </Modal>
      )}
      {dialog === "leave" && (
        <Modal
          title="有未保存的模型配置"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>继续编辑</Button>
              <Button
                onClick={() => {
                  const next = pending.current;
                  setDialog(null);
                  next?.(registry);
                }}
              >
                放弃修改并继续
              </Button>
              <Button
                variant="primary"
                disabled={blocked}
                onClick={() => {
                  const saved = save();
                  if (saved) {
                    const next = pending.current;
                    setDialog(null);
                    next?.(saved);
                  }
                }}
              >
                保存并继续
              </Button>
            </>
          }
        >
          <p>切换模型、用途或离开页面前，请选择如何处理当前修改。</p>
          {error && <p role="alert">{error}</p>}
        </Modal>
      )}
      {dialog === "disable" && (
        <Modal
          title="停用已选择的模型？"
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>取消</Button>
              <Button
                variant="danger"
                onClick={() => {
                  try {
                    persist(
                      setModelEnabled(registry, disableId.current, false),
                    );
                    setDialog(null);
                    const changed = registry.models.find(
                      (m) => m.id === form?.id,
                    );
                    if (changed && changed.id === disableId.current)
                      setEditor({ ...changed, enabled: false });
                    setNotice(
                      "已停用并取消该用途的选择；不会自动替换模型，不影响历史运行。 ",
                    );
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                停用并取消选择
              </Button>
            </>
          }
        >
          <p>
            会取消该用途的待接入选择，不会自动选择其它模型，也不会改变已有技能与运行快照。
          </p>
          {error && <p role="alert">{error}</p>}
        </Modal>
      )}
    </AppShell>
  );
}
