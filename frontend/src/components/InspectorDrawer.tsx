import { CheckCircleIcon, InfoIcon, XIcon } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";
import { Button, IconButton } from "./ui";
import {
  colorNames,
  modeNames,
  type EvidenceMode,
  type SkillDocument,
} from "../data/document";
import { type EditorForm } from "../data/editor";
import { applyEditorForm } from "../data/editor";
import {
  evidenceContext,
  evidenceNeedsReview,
  generatedSemanticQuery,
} from "../data/evidenceBinding";
import { partNames, ruleSummary } from "../data/ruleSummary";
import {
  TimeFields,
  GroupFields,
  OutputFields,
} from "./editors/AdvancedFields";
export { createEditorForm, type EditorForm } from "../data/editor";

export function InspectorDrawer({
  form,
  document,
  dirty,
  onChange,
  onSave,
  onClose,
  embedded = false,
  onEditTime,
  onTimeTarget,
}: {
  form: EditorForm;
  document: SkillDocument;
  dirty: boolean;
  onChange: (form: EditorForm) => void;
  onSave: () => void;
  onClose: () => void;
  embedded?: boolean;
  onEditTime?: () => void;
  onTimeTarget?: (id: string) => void;
}) {
  const firstInput = useRef<HTMLDivElement>(null);
  const condition = document.conditions.find((c) => c.id === form.id);
  const branch = document.branches.find((b) => b.id === form.id);
  const title =
    (
      {
        condition: "编辑条件",
        branch: "编辑分支",
        final: "最终判定",
        output: "业务输出",
        description: "修改技能说明",
        time: "时间要求",
        group: "编辑编排组",
      } as Record<string, string>
    )[form.kind] ?? "模型检测";
  const patch = (values: Partial<EditorForm>) =>
    onChange({ ...form, ...values });
  const preview =
    form.kind === "condition" && condition?.kind === "visible_color"
      ? applyEditorForm(document, form)
      : null;
  const previewCondition = preview?.conditions.find((c) => c.id === form.id);
  const needsReview = !!(
    preview &&
    previewCondition &&
    evidenceNeedsReview(preview, previewCondition)
  );
  const currentContext =
    preview && previewCondition
      ? evidenceContext(preview, previewCondition)
      : null;
  useEffect(() => {
    firstInput.current
      ?.querySelector<HTMLElement>("input,select,textarea")
      ?.focus();
  }, [form.id, form.kind]);
  return (
    <aside
      data-editor-kind={form.kind}
      className={`inspector ${embedded ? "embedded" : ""}`}
      aria-label={title}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <header>
        <h2>{title}</h2>
        <IconButton icon={XIcon} label="关闭编辑面板" onClick={onClose} />
      </header>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSave();
        }}
      >
        <div className="inspector-body" ref={firstInput}>
          {!["time", "group"].includes(form.kind) && (
            <div className="editor-context">
              <CheckCircleIcon size={20} />
              <span>
                {branch?.name ??
                  condition?.label ??
                  (form.kind === "final"
                    ? "选择参与最终判定的分支与组"
                    : document.name)}
              </span>
            </div>
          )}
          {form.kind === "time" ? (
            <TimeFields
              form={form}
              document={document}
              onChange={onChange}
              onTarget={onTimeTarget}
            />
          ) : form.kind === "group" ? (
            <GroupFields form={form} document={document} onChange={onChange} />
          ) : form.kind === "description" ? (
            <>
              <div className="notice">
                <InfoIcon size={20} />
                <span>
                  仅修改说明，不会修改目标、条件、时间或输出，也不会重新编排。实际逻辑以规则画布为准。
                </span>
              </div>
              <label>
                技能说明
                <textarea
                  aria-label="技能说明"
                  rows={5}
                  value={form.instruction}
                  onChange={(e) => patch({ instruction: e.target.value })}
                />
              </label>
              <details className="evidence-rule" open>
                <summary>当前条件与组合摘要（只读，来自配置）</summary>
                <ul>
                  {ruleSummary(document).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </details>
              <Button disabled title="尚未接入编排模型，不会生成或替换规则">
                按描述重新编排（未接入）
              </Button>
              <p className="field-help">
                要改变实际规则，请编辑画布中的条件、时间、编排或业务输出。
              </p>
            </>
          ) : form.kind === "condition" && condition ? (
            <>
              <label>
                条件名称
                <input
                  value={form.name}
                  onChange={(e) => patch({ name: e.target.value })}
                  required
                />
              </label>
              <label>
                作用对象
                <select
                  aria-label="作用对象"
                  value={form.source}
                  onChange={(e) => patch({ source: e.target.value })}
                >
                  {document.entitySources.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label} · 每个目标分别判断
                    </option>
                  ))}
                  {condition.kind === "count" &&
                    document.conditions
                      .filter((c) => c.kind === "inside")
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.label} · 目标集合
                        </option>
                      ))}
                </select>
              </label>
              {condition.kind === "visible_color" ? (
                <>
                  <label>
                    判断部位
                    <select
                      aria-label="判断部位"
                      value={form.part}
                      onChange={(e) => patch({ part: e.target.value })}
                    >
                      <option value="whole">整个目标</option>
                      <option value="upper">上半区域</option>
                      <option value="lower">下半区域</option>
                    </select>
                  </label>
                  <label>
                    颜色
                    <select
                      aria-label="颜色"
                      value={form.color}
                      onChange={(e) => patch({ color: e.target.value })}
                    >
                      {Object.entries(colorNames).map(([value, label]) => (
                        <option value={value} key={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    颜色至少占该部位
                    <div className="input-with-unit">
                      <input
                        aria-label="颜色至少占该部位"
                        type="number"
                        min="0"
                        max="100"
                        step="1"
                        value={form.fraction}
                        onChange={(e) =>
                          patch({ fraction: Number(e.target.value) })
                        }
                        required
                      />
                      <span>%</span>
                    </div>
                    <small>
                      在当前主体的指定部位内复核，不是整张图片的占比。
                    </small>
                  </label>
                  <fieldset>
                    <legend>证据如何组合</legend>
                    {Object.entries(modeNames).map(([value, label]) => (
                      <label className="radio-row" key={value}>
                        <input
                          type="radio"
                          name="evidence-mode"
                          checked={form.evidenceMode === value}
                          onChange={() =>
                            patch({ evidenceMode: value as EvidenceMode })
                          }
                        />
                        {label}
                      </label>
                    ))}
                  </fieldset>
                  <details className="evidence-rule" open>
                    <summary>条件 A · 颜色占比</summary>
                    <p>
                      在所选目标的
                      {form.part === "upper"
                        ? "上半区域"
                        : form.part === "lower"
                          ? "下半区域"
                          : "整体区域"}
                      检查{colorNames[form.color]}像素占比 ≥ {form.fraction}%。
                    </p>
                  </details>
                  <details className="evidence-rule" open>
                    <summary>条件 B · 模型语义证据 + 同一主体归属</summary>
                    <label>
                      语义短语来源
                      <select
                        aria-label="语义短语来源"
                        value={form.semanticMode}
                        onChange={(e) =>
                          patch({
                            semanticMode: e.target
                              .value as EditorForm["semanticMode"],
                          })
                        }
                      >
                        <option value="custom">自定义短语（保留原文）</option>
                        <option value="generated">
                          跟随目标、颜色和部位生成
                        </option>
                      </select>
                    </label>
                    <label>
                      模型语义短语
                      <input
                        aria-label="模型语义短语"
                        value={
                          form.semanticMode === "generated" && currentContext
                            ? generatedSemanticQuery(currentContext)
                            : form.semanticQuery
                        }
                        readOnly={form.semanticMode === "generated"}
                        onChange={(e) =>
                          patch({ semanticQuery: e.target.value })
                        }
                        required
                      />
                    </label>
                    {form.semanticMode === "generated" && (
                      <p className="field-help">
                        仅按当前配置生成短语模板，不会调用模型；这不代表识别效果已验证。
                      </p>
                    )}
                    <p>
                      语义证据必须匹配回条件 A
                      的同一目标。本页只编辑配置，不执行识别。
                    </p>
                  </details>
                  {needsReview && currentContext && (
                    <div className="evidence-review" role="alert">
                      <strong>自定义语义证据待核对</strong>
                      <p>
                        当前：
                        {document.entitySources.find(
                          (s) => s.id === form.source,
                        )?.label ?? form.source}{" "}
                        · {colorNames[form.color]} ·{" "}
                        {partNames[form.part] ?? form.part}
                        。自定义短语未被覆盖，请核对条件名称和短语是否仍适用。
                      </p>
                      <p>
                        {form.evidenceMode === "fraction_only"
                          ? "当前只用颜色占比；重新启用语义证据前仍需核对。"
                          : "可先保存草稿，但核对前不能应用此条件。"}
                      </p>
                      <Button
                        onClick={() =>
                          patch({ semanticReviewedContext: currentContext })
                        }
                      >
                        已核对，保留当前自定义短语
                      </Button>
                    </div>
                  )}
                  <div className="formula">
                    {form.evidenceMode === "all"
                      ? "(A) AND (B)"
                      : form.evidenceMode === "any"
                        ? "(A) OR (B)"
                        : form.evidenceMode === "fraction_only"
                          ? "(A)"
                          : "(B)"}
                  </div>
                </>
              ) : condition.kind === "count" ? (
                <>
                  <div className="field-readonly">
                    <span>作用范围</span>
                    <strong>
                      {document.conditions.find((c) => c.id === form.source)
                        ?.label ?? "所选目标"}{" "}
                      · 每个集合单独计数
                    </strong>
                  </div>
                  <label>
                    至少有多少人
                    <input
                      type="number"
                      min="1"
                      max="9999"
                      step="1"
                      value={form.count}
                      onChange={(e) => patch({ count: Number(e.target.value) })}
                      required
                    />
                  </label>
                </>
              ) : (
                <label>
                  标注区域
                  <select
                    value={form.region}
                    onChange={(e) => patch({ region: e.target.value })}
                  >
                    <option value="">请选择区域</option>
                    {document.regions
                      .filter((r) => r.type !== "direction")
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                          {r.saved ? " · 已保存" : " · 待标注"}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              {onEditTime && (
                <Button onClick={onEditTime}>
                  时间要求 ·{" "}
                  {condition.time?.mode && condition.time.mode !== "immediate"
                    ? "已设置"
                    : "不额外等待"}
                </Button>
              )}
            </>
          ) : form.kind === "branch" ? (
            <>
              <label>
                分支名称
                <input
                  value={form.name}
                  onChange={(e) => patch({ name: e.target.value })}
                  required
                />
              </label>
              <fieldset>
                <legend>分支内条件组合</legend>
                {["AND", "OR"].map((op) => (
                  <label className="radio-row" key={op}>
                    <input
                      type="radio"
                      name="branch-op"
                      checked={form.operator === op}
                      onChange={() => patch({ operator: op })}
                    />
                    {op === "AND"
                      ? "全部条件满足（AND）"
                      : "任一条件满足（OR）"}
                  </label>
                ))}
              </fieldset>
              <div className="field-readonly">
                <span>作用范围</span>
                <strong>
                  {branch?.identity === "per_region"
                    ? "区域2内的人员集合，按区域判断"
                    : "当前来源的每个目标，逐个判断"}
                </strong>
              </div>
              <label>
                何时算分支成立
                <select
                  value={form.timeMode}
                  onChange={(e) => patch({ timeMode: e.target.value })}
                >
                  <option value="immediate">当前画面满足即可</option>
                  <option
                    value="continuous"
                    disabled={document.mediaMode === "image"}
                  >
                    连续满足一段时间
                  </option>
                </select>
              </label>
              {form.timeMode === "continuous" && (
                <>
                  <label>
                    连续满足（秒）
                    <input
                      type="number"
                      min=".1"
                      step=".1"
                      value={form.duration}
                      onChange={(e) =>
                        patch({ duration: Number(e.target.value) })
                      }
                      required
                    />
                  </label>
                  <label>
                    允许短暂中断（秒）
                    <input
                      type="number"
                      min="0"
                      step=".1"
                      value={form.gap}
                      onChange={(e) => patch({ gap: Number(e.target.value) })}
                      required
                    />
                  </label>
                </>
              )}
              {onEditTime && (
                <Button onClick={onEditTime}>打开完整时间设置</Button>
              )}
              <p className="field-help">
                仅作用于「{branch?.name}」。海报不会产生真实时序识别结果。
              </p>
            </>
          ) : form.kind === "final" ? (
            <>
              <fieldset>
                <legend>哪些分支满足时产生结果</legend>
                {["AND", "OR"].map((op) => (
                  <label className="radio-row" key={op}>
                    <input
                      type="radio"
                      name="final-op"
                      checked={form.operator === op}
                      onChange={() => patch({ operator: op })}
                    />
                    {op === "AND"
                      ? "分支A与分支B都满足（AND）"
                      : "分支A或分支B满足（OR）"}
                  </label>
                ))}
              </fieldset>
              <fieldset>
                <legend>参与最终判定</legend>
                {[...document.branches, ...document.groups].map((n) => (
                  <label className="radio-row" key={n.id}>
                    <input
                      type="checkbox"
                      checked={form.members.includes(n.id)}
                      onChange={(e) =>
                        patch({
                          members: e.target.checked
                            ? [...form.members, n.id]
                            : form.members.filter((id) => id !== n.id),
                        })
                      }
                    />
                    {n.name}
                  </label>
                ))}
              </fieldset>
              <p className="field-help">
                这里组合有效结果，不表示先后顺序；顺序请在编排组中显式设置。
              </p>
            </>
          ) : form.kind === "output" ? (
            <OutputFields form={form} document={document} onChange={onChange} />
          ) : (
            <>
              <div className="field-readonly">
                <span>模型输入类别</span>
                <strong>
                  {document.entitySources.map((s) => s.category).join(", ")}
                </strong>
              </div>
              <div className="notice">
                <InfoIcon size={20} />
                <span>
                  仅前端配置演示，不会调用模型。真实执行层的多类别合并推理尚未接入。
                </span>
              </div>
            </>
          )}
          <div className="save-explanation">
            <strong>{dirty ? "有未保存的表单修改" : "尚未修改当前表单"}</strong>
            <p>
              保存仅更新草稿。需点击顶部“校验并应用”，才会改变当前运行版本。
            </p>
          </div>
        </div>
        <footer>
          <Button onClick={onClose}>取消</Button>
          <button className="button primary" type="submit">
            保存到草稿
          </button>
        </footer>
      </form>
    </aside>
  );
}
