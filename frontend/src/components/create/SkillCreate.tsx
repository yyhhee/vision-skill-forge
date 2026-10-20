import { useEffect, useRef, useState } from "react";
import {
  ArrowClockwiseIcon,
  CheckCircleIcon,
  CaretRightIcon,
  FloppyDiskIcon,
  InfoIcon,
  MapPinIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { AppShell } from "../AppShell";
import { Button, Modal } from "../ui";
import { CreationPreview } from "./CreationPreview";
import {
  creationExample,
  creationSignature,
  persistCreation,
  previewCreation,
  type CreationInput,
} from "../../data/creation";
import type { SkillDocument } from "../../data/document";
import { useHistoryLeaveGuard } from "../../data/navigation";

export function SkillCreate({
  fixture,
  navigate,
}: {
  fixture: string;
  navigate: (url: string) => void;
}) {
  const [input, setInput] = useState<CreationInput>({
    instruction: fixture ? creationExample : "",
    name: fixture ? "区域告警" : "",
    mediaMode: "video_demo",
  });
  const [preview, setPreview] = useState<{
    signature: string;
    document: SkillDocument;
  } | null>(() =>
    fixture
      ? {
          signature: creationSignature(input),
          document: previewCreation(input),
        }
      : null,
  );
  const [savedId, setSavedId] = useState("");
  const saving = useRef(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [leave, setLeave] = useState<(() => void) | null>(null);
  const current =
    preview?.signature === creationSignature(input) ? preview.document : null;
  const dirty = !fixture && !savedId && !!(input.instruction || input.name);
  const requestLeave = (proceed: () => void) => {
    if (dirty) {
      setLeave(() => proceed);
      return true;
    }
    proceed();
    return false;
  };
  useHistoryLeaveGuard((proceed) => {
    if (!dirty) return false;
    setLeave(() => proceed);
    return true;
  });
  useEffect(() => {
    const before = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", before);
    const title = document.title;
    document.title = "Vision Skill Forge · 一句话创建";
    return () => {
      window.removeEventListener("beforeunload", before);
      document.title = title;
    };
  }, [dirty]);
  const change = (patch: Partial<CreationInput>) => {
    setInput((v) => ({ ...v, ...patch }));
    setPreview(null);
    setError("");
  };
  const generate = () => {
    try {
      const document = previewCreation(input);
      setPreview({ signature: creationSignature(input), document });
      setError("");
    } catch (e) {
      setPreview(null);
      setError((e as Error).message);
    }
  };
  const save = () => {
    if (fixture) {
      setInfo("这是隔离演示，不写入正常技能数据。请从技能库新建来保存。");
      return "";
    }
    if (savedId) return savedId;
    if (!current || saving.current) return "";
    saving.current = true;
    try {
      const id = persistCreation(current);
      setSavedId(id);
      setError("");
      return id;
    } catch (e) {
      setError((e as Error).message);
      return "";
    } finally {
      saving.current = false;
    }
  };
  const next = (view: string) => {
    if (fixture) {
      setInfo("这是隔离演示，不创建正常技能。请从技能库新建后继续。");
      return;
    }
    const id = save();
    if (id)
      navigate(
        view === "validation"
          ? `/skills/${id}/validate`
          : `/skills/${id}/editor?view=${view}`,
      );
  };
  return (
    <AppShell
      title="新建技能"
      dirty={false}
      revision={0}
      showRevision={false}
      onApply={() => {}}
      onRun={() => {}}
      onMenu={() => {}}
      onNavigate={(label) =>
        label === "技能库"
          ? requestLeave(() =>
              navigate(`/skills${fixture ? "?fixture=01" : ""}`),
            )
          : label === "模型接入"
            ? requestLeave(() =>
                navigate(`/settings/models${fixture ? "?fixture=models" : ""}`),
              )
            : label === "能力管理"
              ? requestLeave(() =>
                  navigate(
                    `/settings/capabilities${fixture ? "?fixture=capabilities" : ""}`,
                  ),
                )
              : label === "运行记录"
                ? requestLeave(() =>
                    navigate(`/runs${fixture ? "?fixture=run-history" : ""}`),
                  )
                : setInfo(`${label}总列表尚未实现。当前不会调用模型或后端。`)
      }
      actions={
        <>
          <Button
            icon={FloppyDiskIcon}
            disabled={!current || !!savedId}
            onClick={save}
          >
            保存草稿
          </Button>
          <Button
            variant="primary"
            disabled={!current}
            onClick={() => next("linked")}
          >
            继续编辑规则
          </Button>
        </>
      }
    >
      <main className="creation-page">
        <nav className="workflow-steps" aria-label="创建步骤">
          {["创建", "场景（可选）", "编排", "验证"].map((label, i) => (
            <div key={label} className={i === 0 ? "current" : ""}>
              <button
                aria-current={i === 0 ? "step" : undefined}
                disabled={i === 0 || !current}
                onClick={() =>
                  next(i === 1 ? "scene" : i === 2 ? "linked" : "validation")
                }
              >
                <span className="step-number">{i + 1}</span>
                {label}
              </button>
              {i < 3 && <CaretRightIcon size={19} />}
            </div>
          ))}
        </nav>
        <div className="creation-columns">
          <section className="creation-form panel">
            <h1>用一句话描述你的需求</h1>
            <p className="creation-subtitle">
              只描述识别目标、条件和希望得到的结果。
            </p>
            <div className="creation-input">
              <textarea
                aria-label="需求描述"
                placeholder="描述目标、条件和输出，或选择下方演示示例。"
                value={input.instruction}
                disabled={!!savedId}
                maxLength={300}
                onChange={(e) => change({ instruction: e.target.value })}
              />
              <span aria-live="polite">
                {Array.from(input.instruction).length} / 300
              </span>
            </div>
            <label className="creation-name">
              技能名称
              <input
                value={input.name}
                placeholder="给技能起个名字"
                maxLength={120}
                disabled={!!savedId}
                onChange={(e) => change({ name: e.target.value })}
              />
            </label>
            <fieldset className="creation-media" disabled={!!savedId}>
              <legend>媒体能力</legend>
              <label>
                <input
                  type="radio"
                  name="creation-media"
                  checked={input.mediaMode === "image"}
                  onChange={() => change({ mediaMode: "image" })}
                />
                图片
              </label>
              <label>
                <input
                  type="radio"
                  name="creation-media"
                  checked={input.mediaMode === "video_demo"}
                  onChange={() => change({ mediaMode: "video_demo" })}
                />
                视频<span className="sr-only">（海报模拟，非真实视频）</span>
              </label>
              <label title="当前只支持单一媒体模式">
                <input type="radio" disabled />
                图片和视频
              </label>
            </fieldset>
            <details className="creation-examples">
              <summary>演示示例与高级选项</summary>
              <p>
                当前未连接
                LLM。仅以下原句可预览固定演示规则，不识别其它表达。素材为已确认的施工场景海报，视频仅模拟。
              </p>
              <Button
                disabled={!!savedId}
                onClick={() => {
                  change({
                    instruction: creationExample,
                    name: input.name || "区域告警",
                  });
                }}
              >
                使用区域告警演示示例
              </Button>
              <p>{creationExample}</p>
              <Button
                onClick={() =>
                  requestLeave(() =>
                    navigate(
                      `/skills?create=template${fixture ? "&fixture=01" : ""}`,
                    ),
                  )
                }
              >
                从完整模板新建
              </Button>
            </details>
            <Button
              icon={ArrowClockwiseIcon}
              disabled={!!savedId}
              onClick={generate}
            >
              {preview ? "重新生成演示预览" : "生成演示预览"}
            </Button>
            {error && (
              <p className="creation-error" role="alert">
                {error}
              </p>
            )}
            <div
              className={`creation-notice ${current ? "success" : "pending"}`}
              role="status"
            >
              <>
                {current ? (
                  <CheckCircleIcon size={26} weight="fill" />
                ) : (
                  <InfoIcon size={26} />
                )}
                <div>
                  <strong>
                    {savedId
                      ? "草稿已保存，尚未应用。"
                      : current
                        ? "已生成演示草稿，请确认理解是否正确。"
                        : "尚未连接 LLM，可先体验演示示例。"}
                  </strong>
                  <p>
                    {savedId
                      ? "为避免重复创建，继续修改请进入规则编辑器；再次继续会打开同一个技能。"
                      : current
                        ? "此预览来自明确列出的演示配置，不是模型生成。确认后可继续标注区域或编辑规则。"
                        : "展开上方示例，填入完整演示描述后生成预览。其它描述不会返回伪造的编排。"}
                  </p>
                </div>
              </>
            </div>
          </section>
          <section
            className="creation-understanding panel"
            aria-label="系统理解"
          >
            <h2>系统理解</h2>
            <p className="creation-subtitle">
              {current
                ? "演示预览，以下规则供你核对："
                : "生成预览后，在这里核对目标、条件和输出。"}
            </p>
            {current ? (
              <>
                <CreationPreview document={current} />
                <div className="creation-annotation">
                  <WarningCircleIcon size={30} weight="fill" />
                  <div>
                    <strong>
                      运行前需要标注：
                      {current.regions.map((r) => r.name).join("、")}
                    </strong>
                    <small>请在场景中绘制并保存区域，坐标不会自动生成。</small>
                  </div>
                  <Button icon={MapPinIcon} onClick={() => next("scene")}>
                    定位到场景标注
                  </Button>
                </div>
                <p className="creation-footnote">
                  <InfoIcon size={23} />
                  生成不等于已生效，需审核并应用。
                </p>
              </>
            ) : (
              <div className="creation-empty">
                <SharePreviewIcon />
                <h3>{error ? "这段描述尚未生成规则" : "等待生成理解预览"}</h3>
                <p>不会把未支持的描述替换成区域告警规则。</p>
              </div>
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
      {leave && (
        <Modal
          title="离开新建页面？"
          onClose={() => setLeave(null)}
          footer={
            <>
              <Button onClick={() => setLeave(null)}>继续填写</Button>
              <Button
                onClick={() => {
                  const proceed = leave;
                  setLeave(null);
                  proceed();
                }}
              >
                放弃并离开
              </Button>
              <Button
                variant="primary"
                disabled={!current}
                onClick={() => {
                  if (save()) {
                    const proceed = leave;
                    setLeave(null);
                    proceed();
                  }
                }}
              >
                保存草稿并离开
              </Button>
            </>
          }
        >
          <p>
            尚未保存的需求和预览只保留在当前页面。离开前请选择保存，或明确放弃。
          </p>
          {!current && <p>尚无有效演示预览，不能保存为可编辑技能。</p>}
          {error && <p role="alert">{error}</p>}
        </Modal>
      )}
    </AppShell>
  );
}
function SharePreviewIcon() {
  return <InfoIcon size={36} />;
}
