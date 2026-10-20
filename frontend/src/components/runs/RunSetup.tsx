import {
  CaretRightIcon,
  CaretDownIcon,
  CheckCircleIcon,
  ClockIcon,
  CubeIcon,
  ImageIcon,
  InfoIcon,
  SelectionAllIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import type { SkillDocument } from "../../data/document";
import {
  sampleTimes,
  validateSettings,
  type RunSettings,
} from "../../data/runs";
import { Button } from "../ui";
import { RunMedia } from "./RunMedia";
import { useState } from "react";
const numberValue = (value: number) => (Number.isFinite(value) ? value : "");

export function RunSetup({
  document,
  revision,
  settings,
  dirty,
  workspaceDirty,
  onChange,
  onSave,
  onApply,
  onBack,
  onPrevious,
}: {
  document: SkillDocument;
  revision: number;
  settings: RunSettings;
  dirty: boolean;
  workspaceDirty: boolean;
  onChange: (s: RunSettings) => void;
  onSave: () => void;
  onApply: () => void;
  onBack: () => void;
  onPrevious?: () => void;
}) {
  const [previewTime, setPreviewTime] = useState(0);
  const update = (patch: Partial<RunSettings>) =>
    onChange({ ...settings, ...patch });
  const updateTile = (patch: Partial<RunSettings["tiles"]>) =>
    update({ tiles: { ...settings.tiles, ...patch } });
  const errors = validateSettings(settings);
  return (
    <main className="run-page setup-page">
      <nav className="workflow-steps" aria-label="技能创建步骤">
        {["创建", "场景（可选）", "编排", "验证"].map((label, index) => (
          <div className={index === 3 ? "current" : ""} key={label}>
            <button
              aria-current={index === 3 ? "step" : undefined}
              disabled={index < 2}
              onClick={index === 2 ? onBack : undefined}
            >
              <span className="step-number">{index + 1}</span>
              {label}
            </button>
            {index < 3 && <CaretRightIcon size={19} />}
          </div>
        ))}
      </nav>
      <div className="run-notice">
        <InfoIcon size={23} />
        <span>
          本次使用 <strong>R{revision}</strong>；不会使用未应用草稿。
          <small>纯前端脚本演示，不调用模型。</small>
        </span>
      </div>
      <div className="run-setup-grid">
        <section className="panel run-card setup-media">
          <header>
            <h2>验证素材</h2>
            <span className="media-pill">本地演示海报</span>
          </header>
          <RunMedia
            document={document}
            time={previewTime}
            onTime={setPreviewTime}
          />
          <h3>施工场景海报</h3>
          <p className="muted">1448 × 1086 · 4:3 · 模拟时长30秒</p>
          <div className="run-success">
            <CheckCircleIcon size={25} />
            <div>
              <strong>
                {document.regions
                  .filter((r) => r.saved)
                  .map((r) => r.name)
                  .join("、")}{" "}
                已保存
              </strong>
              <p>素材与区域来自当前运行快照。</p>
            </div>
          </div>
          {onPrevious && <Button onClick={onPrevious}>查看上次模拟运行</Button>}
        </section>
        <section className="panel run-card settings-card">
          <header>
            <h2>验证配置</h2>
            <span className="run-model-tag">
              <CubeIcon size={19} />
              视觉演示适配器 · 未连接
            </span>
          </header>
          <details className="run-section">
            <summary>
              <ImageIcon size={24} />
              <strong>抽帧</strong>
              <span>
                每{settings.sampleIntervalSeconds}秒1帧 ·{" "}
                {settings.startSeconds}–{settings.endSeconds}秒
              </span>
              <CaretDownIcon className="run-section-chevron" size={17} />
            </summary>
            <div className="run-form-grid">
              <label>
                采样间隔（秒）
                <input
                  type="number"
                  min=".1"
                  max="30"
                  step=".1"
                  value={numberValue(settings.sampleIntervalSeconds)}
                  onChange={(e) =>
                    update({ sampleIntervalSeconds: e.target.valueAsNumber })
                  }
                />
              </label>
              <label>
                最大采样帧数
                <input
                  type="number"
                  min="0"
                  max="300"
                  value={numberValue(settings.maxFrames)}
                  onChange={(e) =>
                    update({ maxFrames: e.target.valueAsNumber })
                  }
                />
                <small>0表示不限</small>
              </label>
              <label>
                开始时间（秒）
                <input
                  type="number"
                  min="0"
                  max="29.9"
                  step=".1"
                  value={numberValue(settings.startSeconds)}
                  onChange={(e) =>
                    update({ startSeconds: e.target.valueAsNumber })
                  }
                />
              </label>
              <label>
                结束时间（秒，不含）
                <input
                  type="number"
                  min=".1"
                  max="30"
                  step=".1"
                  value={numberValue(settings.endSeconds)}
                  onChange={(e) =>
                    update({ endSeconds: e.target.valueAsNumber })
                  }
                />
              </label>
            </div>
            <p className="field-explanation sampling-explanation">
              采样帧数 ≠ 切片数 ≠
              模型请求数；这里不估算模型耗时。模拟范围采用左闭右开区间。
            </p>
          </details>
          <details className="run-section">
            <summary>
              <SelectionAllIcon size={24} />
              <strong>缩放</strong>
              <span>保持比例 · 长边{settings.resizeLongEdge}</span>
              <CaretDownIcon className="run-section-chevron" size={17} />
            </summary>
            <label className="run-single-field">
              缩放长边（像素）
              <input
                type="number"
                min="320"
                max="4096"
                value={numberValue(settings.resizeLongEdge)}
                onChange={(e) =>
                  update({ resizeLongEdge: e.target.valueAsNumber })
                }
              />
              <small>仅保存演示配置，不执行图像推理预处理。</small>
            </label>
          </details>
          <details className="run-section" open>
            <summary>
              <SquaresFourIcon size={24} />
              <strong>切片与去重</strong>
              <CaretDownIcon className="run-section-chevron" size={17} />
            </summary>
            <div className="tile-body">
              <div className="run-checkbox-row">
                <label>
                  <input
                    type="checkbox"
                    checked={settings.tiles.enabled}
                    onChange={(e) => updateTile({ enabled: e.target.checked })}
                  />
                  启用切片
                </label>
                <label>
                  <input
                    type="checkbox"
                    disabled={!settings.tiles.enabled}
                    checked={settings.tiles.includeFullFrame}
                    onChange={(e) =>
                      updateTile({ includeFullFrame: e.target.checked })
                    }
                  />
                  保留整图检测
                </label>
              </div>
              <fieldset
                disabled={!settings.tiles.enabled}
                className="run-form-grid tile-fields"
              >
                <label>
                  切片宽（像素）
                  <input
                    type="number"
                    min="128"
                    max="4096"
                    value={numberValue(settings.tiles.width)}
                    onChange={(e) =>
                      updateTile({ width: e.target.valueAsNumber })
                    }
                  />
                </label>
                <label>
                  切片高（像素）
                  <input
                    type="number"
                    min="128"
                    max="4096"
                    value={numberValue(settings.tiles.height)}
                    onChange={(e) =>
                      updateTile({ height: e.target.valueAsNumber })
                    }
                  />
                </label>
                <label>
                  横向覆盖（%）
                  <input
                    type="number"
                    min="0"
                    max="90"
                    value={numberValue(
                      Math.round(settings.tiles.overlapX * 100),
                    )}
                    onChange={(e) =>
                      updateTile({ overlapX: e.target.valueAsNumber / 100 })
                    }
                  />
                </label>
                <label>
                  纵向覆盖（%）
                  <input
                    type="number"
                    min="0"
                    max="90"
                    value={numberValue(
                      Math.round(settings.tiles.overlapY * 100),
                    )}
                    onChange={(e) =>
                      updateTile({ overlapY: e.target.valueAsNumber / 100 })
                    }
                  />
                </label>
              </fieldset>
              <p className="field-explanation">
                相邻切片重复覆盖的范围，不决定框是否合并。
              </p>
              <div className="dedup-row">
                <fieldset>
                  <legend>去重方式</legend>
                  {[
                    ["instance", "实例级融合"],
                    ["ios", "IoS"],
                    ["iou", "IoU"],
                  ].map(([value, label]) => (
                    <label key={value}>
                      <input
                        type="radio"
                        name="dedup"
                        checked={settings.dedup.metric === value}
                        onChange={() =>
                          update({
                            dedup: {
                              ...settings.dedup,
                              metric: value as RunSettings["dedup"]["metric"],
                            },
                          })
                        }
                      />
                      {label}
                    </label>
                  ))}
                </fieldset>
                <label>
                  去重阈值
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step=".01"
                    value={numberValue(settings.dedup.threshold)}
                    onChange={(e) =>
                      update({
                        dedup: {
                          ...settings.dedup,
                          threshold: e.target.valueAsNumber,
                        },
                      })
                    }
                  />
                </label>
              </div>
              <details className="algorithm-help">
                <summary>展开算法说明</summary>
                <p>IoU：交集 / 并集；大小、位置接近时较高。</p>
                <p>IoS：交集 / 较小框面积；小框被包含时较高。</p>
                <p>
                  实例级融合：同帧、同类别、同来源实体；IoU达到阈值，或IoS达到max(0.8,
                  阈值)且中心距离不超过较小框对角线25%。
                </p>
                <p>
                  保留定位更好的框：由执行适配器的best_localization策略决定。当前纯前端未执行融合，也不声称已选出最优框。
                </p>
              </details>
            </div>
          </details>
          <details className="run-section">
            <summary>
              <ImageIcon size={24} />
              <strong>输出媒体与证据</strong>
              <CaretDownIcon className="run-section-chevron" size={17} />
            </summary>
            <p className="field-explanation">
              仅提供模拟事件JSON、运行快照与同源海报证据。没有真实视频，不能导出标注视频。
            </p>
          </details>
          <div className="run-estimate">
            <ClockIcon size={22} />
            <span>
              预计采样 {sampleTimes(settings).length} 帧（估算，尚未运行）
            </span>
          </div>
          {errors.length > 0 && (
            <div className="run-error" role="alert">
              {errors.join(" ")}
            </div>
          )}
          {(dirty || workspaceDirty) && (
            <div className="settings-actions">
              <Button disabled={!dirty || !!errors.length} onClick={onSave}>
                保存运行设置到草稿
              </Button>
              <Button
                disabled={(!workspaceDirty && !dirty) || !!errors.length}
                onClick={onApply}
              >
                校验并应用草稿
              </Button>
            </div>
          )}
          {(dirty || workspaceDirty) && (
            <p className="field-explanation">
              {dirty ? "有未保存的运行设置。" : "表单已保存。"}保存不会改变R
              {revision}；应用将连同其它草稿修改一起生成新版本。
            </p>
          )}
        </section>
      </div>
    </main>
  );
}
