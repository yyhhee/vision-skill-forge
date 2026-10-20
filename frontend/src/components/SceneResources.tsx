import {
  CheckCircleIcon,
  PencilSimpleIcon,
  PlusIcon,
  TrashIcon,
  InfoIcon,
} from "@phosphor-icons/react";
import type { SkillDocument } from "../data/document";
import type { EditorForm } from "../data/editor";
import { regionDependents } from "../data/validation";
import { Button, IconButton } from "./ui";
export function SceneResources({
  document: doc,
  selected,
  form,
  onSelect,
  onChange,
  onSave,
  onAdd,
  onDelete,
  onDraw,
}: {
  document: SkillDocument;
  selected: string;
  form: EditorForm | null;
  onSelect: (id: string) => void;
  onChange: (f: EditorForm) => void;
  onSave: () => void;
  onAdd: () => void;
  onDelete: (id: string) => void;
  onDraw: (tool: string) => void;
}) {
  const region = doc.regions.find((r) => r.id === selected);
  return (
    <section className="panel scene-resources" aria-label="标注资源">
      <header className="panel-header">
        <h2>标注资源</h2>
        <Button icon={PlusIcon} onClick={onAdd}>
          新增区域
        </Button>
      </header>
      <div className="resources-body">
        <div className="resource-list">
          {doc.regions.map((r) => (
            <div
              className={`resource-item ${r.id === selected ? "selected" : ""}`}
              key={r.id}
            >
              <button
                aria-label={`编辑资源${r.name}`}
                onClick={() => onSelect(r.id)}
              >
                <span className={`status-dot ${r.colorIdentity}`} />
                <strong>{r.name}</strong>
                {!r.saved && <small>待标注</small>}
              </button>
              <IconButton
                icon={PencilSimpleIcon}
                label={`修改${r.name}名称`}
                onClick={() => onSelect(r.id)}
              />
              <IconButton
                icon={TrashIcon}
                label={`删除${r.name}`}
                onClick={() => onDelete(r.id)}
              />
            </div>
          ))}
        </div>
        {region && form?.kind === "region" && (
          <form
            className="resource-details"
            onSubmit={(e) => {
              e.preventDefault();
              onSave();
            }}
          >
            <h3>区域详情</h3>
            <label>
              名称
              <input
                value={form.name}
                onChange={(e) => onChange({ ...form, name: e.target.value })}
                required
              />
            </label>
            <div className="field-readonly">
              <span>形状</span>
              <strong>
                {region.type === "direction"
                  ? "方向参考"
                  : region.type === "rectangle"
                    ? "矩形"
                    : "多边形"}
              </strong>
            </div>
            <div className="field-readonly">
              <span>用于</span>
              <strong>
                {regionDependents(doc, region.id).join("、") ||
                  "尚未被条件引用"}
              </strong>
            </div>
            <div className="notice">
              <CheckCircleIcon size={21} />
              <span>
                {region.saved ? "已保存标注到草稿" : "尚未完成绘制并保存"} ·{" "}
                {region.points.length}个点<p>草稿标注不改变当前运行快照。</p>
              </span>
            </div>
            <div className="resource-actions">
              <Button onClick={() => onDraw(region.type)}>重新绘制</Button>
              <button className="button primary" type="submit">
                保存资源名称
              </button>
            </div>
          </form>
        )}
        <details className="direction-help">
          <summary>方向参考 · 可选</summary>
          <p>
            新增资源后选择“方向参考”，点击起点与终点并保存。方向线不作为封闭区域，不能用于区域内数量判断。
          </p>
        </details>
        <p className="field-help">
          <InfoIcon size={18} />
          删除前检查引用；被使用的资源不会被静默移除。
        </p>
      </div>
    </section>
  );
}
