import {
  ArrowDownIcon,
  ArrowUpIcon,
  InfoIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { createEditorForm, type EditorForm } from "../../data/editor";
import { type SkillDocument } from "../../data/document";
import { outputTypeNames, resultSources } from "../../data/validation";
import { IconButton } from "../ui";
type Props = {
  form: EditorForm;
  document: SkillDocument;
  onChange: (f: EditorForm) => void;
  onTarget?: (id: string) => void;
};
export function TimeFields({
  form: f,
  document: doc,
  onChange,
  onTarget,
}: Props) {
  const patch = (p: Partial<EditorForm>) => onChange({ ...f, ...p });
  const target =
    doc.conditions.find((c) => c.id === f.targetId) ??
    doc.branches.find((b) => b.id === f.targetId);
  const targetName = target && ("label" in target ? target.label : target.name);
  const sourceOptions =
    f.scopeMode === "per_region"
      ? doc.regions
          .filter((r) => r.type !== "direction")
          .map((r) => ({ id: r.id, label: r.name }))
      : doc.entitySources.map((s) => ({ id: s.id, label: s.label }));
  const timedParent =
    f.targetKind === "condition" &&
    doc.branches.find(
      (b) =>
        b.logic.members.includes(f.targetId) && b.time.mode !== "immediate",
    );
  const timedChildren =
    f.targetKind === "branch" &&
    doc.branches
      .find((b) => b.id === f.targetId)
      ?.logic.members.some((id) =>
        doc.conditions.some(
          (c) => c.id === id && c.time && c.time.mode !== "immediate",
        ),
      );
  return (
    <>
      <h3 className="section-title">
        <span>1</span>设置作用范围
      </h3>
      <fieldset>
        <legend>作用层级</legend>
        {[
          ["condition", "某个条件"],
          ["branch", "整个分支"],
        ].map(([v, l]) => (
          <label className="radio-row" key={v}>
            <input
              type="radio"
              name="time-layer"
              checked={f.targetKind === v}
              onChange={() => {
                const item =
                  v === "condition" ? doc.conditions[0] : doc.branches[0];
                if (onTarget) {
                  onTarget(item.id);
                  return;
                }
                onChange({
                  ...createEditorForm(doc, item.id, "time"),
                  targetKind: v,
                  targetId: item.id,
                });
              }}
            />
            {l}
          </label>
        ))}
      </fieldset>
      <label>
        {f.targetKind === "condition" ? "作用条件" : "作用分支"}
        <select
          value={f.targetId}
          onChange={(e) =>
            onTarget
              ? onTarget(e.target.value)
              : onChange(createEditorForm(doc, e.target.value, "time"))
          }
        >
          {(f.targetKind === "condition"
            ? doc.conditions.map((c) => ({ id: c.id, name: c.label }))
            : doc.branches
          ).map((n) => (
            <option key={n.id} value={n.id}>
              {n.name}
            </option>
          ))}
        </select>
      </label>
      <div className="editor-context">仅对「{targetName}」的结果计时。</div>
      <h3 className="section-title">
        <span>2</span>设置时间要求
      </h3>
      <label>
        时间模式
        <select
          value={f.timeMode}
          onChange={(e) => patch({ timeMode: e.target.value })}
        >
          {[
            ["immediate", "当前画面满足即可"],
            ["continuous", "连续满足一段时间"],
            ["cumulative", "窗口内累计满足"],
            ["ratio", "窗口内满足比例"],
            ["repeat", "窗口内满足指定次数"],
          ].map(([v, l]) => (
            <option
              key={v}
              value={v}
              disabled={doc.mediaMode === "image" && v !== "immediate"}
            >
              {l}
            </option>
          ))}
        </select>
      </label>
      {f.timeMode !== "immediate" && (
        <>
          {["cumulative", "ratio", "repeat"].includes(f.timeMode) && (
            <label>
              观察窗口（秒）
              <input
                type="number"
                min=".1"
                step=".1"
                value={f.window}
                onChange={(e) => patch({ window: Number(e.target.value) })}
                required
              />
            </label>
          )}
          {["continuous", "cumulative"].includes(f.timeMode) && (
            <>
              <label>
                {f.timeMode === "continuous"
                  ? "连续满足（秒）"
                  : "累计满足（秒）"}
                <input
                  type="number"
                  min=".1"
                  step=".1"
                  value={f.duration}
                  onChange={(e) => patch({ duration: Number(e.target.value) })}
                  required
                />
              </label>
              <label>
                允许短暂中断（秒）
                <input
                  type="number"
                  min="0"
                  step=".1"
                  value={f.gap}
                  onChange={(e) => patch({ gap: Number(e.target.value) })}
                  required
                />
              </label>
            </>
          )}
          {f.timeMode === "ratio" && (
            <label>
              窗口满足比例（%）
              <input
                type="number"
                min=".1"
                max="100"
                step=".1"
                value={f.ratio}
                onChange={(e) => patch({ ratio: Number(e.target.value) })}
                required
              />
            </label>
          )}
          {f.timeMode === "repeat" && (
            <>
              <label>
                满足次数
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={f.repeats}
                  onChange={(e) => patch({ repeats: Number(e.target.value) })}
                  required
                />
              </label>
              <small>
                从“不满足”到“满足”算一次；连续多帧满足不会重复累计。
              </small>
            </>
          )}
          <label>
            按谁分别计时
            <select
              value={f.scopeMode}
              onChange={(e) =>
                patch({
                  scopeMode: e.target.value,
                  scopeSource:
                    e.target.value === "per_region"
                      ? (doc.regions[0]?.id ?? "")
                      : e.target.value === "global_scene"
                        ? "scene"
                        : (doc.entitySources[0]?.id ?? ""),
                })
              }
            >
              <option value="per_entity">同一来源中的每个目标</option>
              <option value="per_region">每个标注区域</option>
              <option value="global_scene">当前画面整体</option>
              <option
                value="per_track"
                disabled={!doc.entitySources.some((s) => s.trackAvailable)}
              >
                同一轨迹（
                {doc.entitySources.some((s) => s.trackAvailable)
                  ? "可用"
                  : "缺少跟踪来源"}
                ）
              </option>
            </select>
          </label>
          {f.scopeMode !== "global_scene" && (
            <label>
              具体计时来源
              <select
                value={f.scopeSource}
                onChange={(e) => patch({ scopeSource: e.target.value })}
              >
                <option value="">请选择来源</option>
                {sourceOptions.map((s) => (
                  <option value={s.id} key={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              <small>
                来源内若有多个目标或区域，各自计时，不混为一个对象。
              </small>
            </label>
          )}
        </>
      )}
      <h3 className="section-title">
        <span>3</span>成立后的有效期
      </h3>
      <label>
        满足后保持多久
        <select
          value={f.validity}
          onChange={(e) => patch({ validity: e.target.value })}
        >
          <option value="current_frame">仅当前采样时刻有效</option>
          <option value="hold">成立后再保持一段时间</option>
          <option value="until_end">保持到当前媒体结束</option>
        </select>
      </label>
      {f.validity === "hold" && (
        <label>
          保持时长（秒）
          <input
            type="number"
            min=".1"
            step=".1"
            value={f.hold}
            onChange={(e) => patch({ hold: Number(e.target.value) })}
            required
          />
        </label>
      )}
      {(timedParent || timedChildren) && (
        <div className="notice warning-text">
          <InfoIcon size={20} />
          <span>
            此路径的条件和分支均有时间要求，会先计算条件时间，再计算分支时间。若不希望叠加，请将其中一层设为“当前画面满足即可”。
          </span>
        </div>
      )}
      <div className="evidence-rule">
        <strong>规则预览</strong>
        <p>
          「{targetName}」
          {f.timeMode === "immediate"
            ? "当前画面满足即可"
            : f.timeMode === "continuous"
              ? `连续满足 ${f.duration} 秒，允许中断 ${f.gap} 秒`
              : f.timeMode === "cumulative"
                ? `${f.window} 秒内累计满足 ${f.duration} 秒`
                : f.timeMode === "ratio"
                  ? `${f.window} 秒窗口内满足比例达到 ${f.ratio}%`
                  : `${f.window} 秒内满足 ${f.repeats} 次`}
          。
          {f.validity === "hold"
            ? `成立后保持 ${f.hold} 秒。`
            : f.validity === "until_end"
              ? "有效至本媒体结束。"
              : "仅当前采样时刻有效。"}
        </p>
      </div>
      <small>
        当前为视频配置演示，海报不产生真实时间事件；保存不会给其它条件或分支复制计时。
      </small>
    </>
  );
}
export function GroupFields({ form: f, document: doc, onChange }: Props) {
  const patch = (p: Partial<EditorForm>) => onChange({ ...f, ...p });
  const options = [...doc.branches, ...doc.groups].filter((n) => n.id !== f.id);
  const reorder = (index: number, delta: number) => {
    const members = [...f.members];
    [members[index], members[index + delta]] = [
      members[index + delta],
      members[index],
    ];
    patch({ members });
  };
  return (
    <>
      <label>
        名称
        <input
          value={f.name}
          onChange={(e) => patch({ name: e.target.value })}
          required
        />
      </label>
      <label>
        基础关系
        <select
          value={f.operator}
          onChange={(e) => patch({ operator: e.target.value })}
        >
          <option value="AND">全部同时有效（AND）</option>
          <option value="OR">任一有效（OR）</option>
          <option value="NOT">不满足（NOT，单成员）</option>
          <option value="SEQUENCE" disabled={doc.mediaMode === "image"}>
            按顺序发生
          </option>
        </select>
      </label>
      <small>
        {f.operator === "SEQUENCE"
          ? "只有显式顺序关系才有前后次序；普通依赖线不表示顺序。"
          : "并行表示结果的逻辑组合，不保证模型请求物理并发。"}
      </small>
      <h3>
        成员
        {f.operator === "SEQUENCE" ? "（按顺序）" : "（可引用已保存编排组）"}
      </h3>
      <ol className="group-member-list">
        {f.members.map((id, index) => (
          <li key={id}>
            <span>{index + 1}</span>
            <strong>
              {options.find((n) => n.id === id)?.name ?? "来源已不存在"}
            </strong>
            <IconButton
              icon={ArrowUpIcon}
              label={`上移步骤${index + 1}`}
              disabled={index === 0}
              onClick={() => reorder(index, -1)}
            />
            <IconButton
              icon={ArrowDownIcon}
              label={`下移步骤${index + 1}`}
              disabled={index === f.members.length - 1}
              onClick={() => reorder(index, 1)}
            />
            <IconButton
              icon={TrashIcon}
              label={`移除步骤${index + 1}`}
              onClick={() =>
                patch({ members: f.members.filter((n) => n !== id) })
              }
            />
          </li>
        ))}
      </ol>
      <label>
        添加成员
        <select
          value=""
          onChange={(e) => {
            if (e.target.value)
              patch({ members: [...f.members, e.target.value] });
          }}
        >
          <option value="">选择分支或已保存组</option>
          {options
            .filter((n) => !f.members.includes(n.id))
            .map((n) => (
              <option key={n.id} value={n.id}>
                {n.name}
              </option>
            ))}
        </select>
      </label>
      {f.operator === "SEQUENCE" && (
        <>
          <label>
            前一步从哪个时刻开始算间隔
            <select
              value={f.anchor}
              onChange={(e) => patch({ anchor: e.target.value })}
            >
              <option value="previous.start">前一步开始</option>
              <option value="previous.qualified">前一步达到成立条件</option>
              <option value="previous.end">前一步结束</option>
            </select>
          </label>
          <div className="field-readonly">
            <span>后一步锚点</span>
            <strong>后一步开始</strong>
          </div>
          <label>
            最短间隔（秒）
            <input
              type="number"
              min="0"
              step=".1"
              value={f.minGap}
              onChange={(e) => patch({ minGap: Number(e.target.value) })}
              required
            />
          </label>
          <label>
            最长间隔（秒）
            <input
              type="number"
              min="0"
              step=".1"
              value={f.maxGap}
              onChange={(e) => patch({ maxGap: Number(e.target.value) })}
              required
            />
          </label>
          <label>
            关联对象
            <select
              value={f.scopeMode}
              onChange={(e) =>
                patch({
                  scopeMode: e.target.value,
                  scopeSource:
                    e.target.value === "global_scene"
                      ? "scene"
                      : (doc.entitySources[0]?.id ?? ""),
                })
              }
            >
              <option value="global_scene">当前媒体整体</option>
              <option value="per_entity">同一目标来源</option>
              <option
                value="per_track"
                disabled={!doc.entitySources.some((s) => s.trackAvailable)}
              >
                同一轨迹（无跟踪来源时不可选）
              </option>
            </select>
          </label>
          {f.scopeMode !== "global_scene" && (
            <label>
              关联来源
              <select
                value={f.scopeSource}
                onChange={(e) => patch({ scopeSource: e.target.value })}
              >
                {doc.entitySources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            完成后有效期
            <select
              value={f.validity}
              onChange={(e) => patch({ validity: e.target.value })}
            >
              <option value="current_frame">仅完成时刻</option>
              <option value="hold">完成后保持一段时间</option>
              <option value="until_end">到媒体结束</option>
            </select>
          </label>
          {f.validity === "hold" && (
            <label>
              保持时长（秒）
              <input
                type="number"
                min=".1"
                step=".1"
                value={f.hold}
                onChange={(e) => patch({ hold: Number(e.target.value) })}
                required
              />
            </label>
          )}
        </>
      )}
      <div className="evidence-rule">
        <strong>依赖关系</strong>
        <p>
          本组使用：
          {f.members
            .map((id) => options.find((n) => n.id === id)?.name ?? "无效来源")
            .join("、") || "尚未选择成员"}
        </p>
        <p>
          被引用于：
          {[
            ...doc.groups
              .filter((g) => g.members.includes(f.id))
              .map((g) => g.name),
            ...(doc.final.members.includes(f.id) ? ["最终判定"] : []),
          ].join("、") || "尚未被引用"}
        </p>
      </div>
    </>
  );
}
export function OutputFields({ form: f, document: doc, onChange }: Props) {
  const patch = (p: Partial<EditorForm>) => onChange({ ...f, ...p });
  const sources = resultSources(doc);
  const compatible = sources.find((s) => s.id === f.source)?.types ?? [];
  return (
    <>
      <label>
        输出名称
        <input
          value={f.name}
          onChange={(e) => patch({ name: e.target.value })}
          required
        />
      </label>
      <label>
        结果来源
        <select
          aria-label="结果来源"
          value={f.source ?? ""}
          onChange={(e) => patch({ source: e.target.value })}
        >
          <option value="">请选择结果来源</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        输出类型
        <select
          aria-label="输出类型"
          value={f.resultType}
          onChange={(e) => patch({ resultType: e.target.value })}
        >
          {Object.entries(outputTypeNames).map(([v, l]) => (
            <option key={v} value={v} disabled={!compatible.includes(v)}>
              {l}
              {!compatible.includes(v) ? " · 与当前来源不兼容" : ""}
            </option>
          ))}
        </select>
      </label>
      {!compatible.includes(f.resultType) && (
        <p role="alert" className="warning-text">
          来源与输出类型不兼容，请选择兼容类型后保存。
        </p>
      )}
      <label>
        证据保存
        <select
          value={f.evidence}
          onChange={(e) => patch({ evidence: e.target.value })}
        >
          <option value="best_effort">尽量保存可用证据</option>
          <option value="none">不保存证据</option>
        </select>
      </label>
      <label className="radio-row">
        <input
          type="checkbox"
          checked={f.showInSummary}
          onChange={(e) => patch({ showInSummary: e.target.checked })}
        />
        在结果总览展示
      </label>
      <h3>触发方式</h3>
      <label>
        什么时候产生结果
        <select
          value={f.trigger}
          onChange={(e) => patch({ trigger: e.target.value })}
        >
          <option value="once_per_episode">每次成立周期产生一个</option>
          <option value="first_only">本媒体首次满足时产生一个</option>
          <option value="every_match">每个满足时刻均产生</option>
        </select>
      </label>
      <small>
        成立周期从“不满足→满足”开始，到“不再满足且有效期结束”为止；持续满足不算新周期。
      </small>
      <label>
        冷却时间（秒）
        <input
          type="number"
          min="0"
          step="1"
          value={f.cooldown}
          onChange={(e) => patch({ cooldown: Number(e.target.value) })}
          required
        />
      </label>
      <div className="notice">
        <InfoIcon size={20} />
        <span>仅本地展示。外部通知未接入，不会发送真实告警。</span>
      </div>
    </>
  );
}
