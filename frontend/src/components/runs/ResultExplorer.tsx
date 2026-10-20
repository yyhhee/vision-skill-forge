import { useState } from "react";
import {
  ArrowSquareOutIcon,
  DownloadSimpleIcon,
  FileTextIcon,
  InfoIcon,
  PlayCircleIcon,
  TShirtIcon,
  PantsIcon,
  UsersIcon,
} from "@phosphor-icons/react";
import {
  downloadJson,
  formatTime,
  poster,
  type DemoEvidence,
  type DemoRun,
} from "../../data/runs";
import { Button, Modal } from "../ui";
import { RunMedia } from "./RunMedia";

function EvidenceCrop({ evidence }: { evidence: DemoEvidence }) {
  const [x, y, w, h] = evidence.crop;
  return (
    <div
      className="evidence-crop"
      style={{ aspectRatio: `${w * 1448}/${h * 1086}` }}
    >
      <img
        src={poster}
        alt={`${evidence.label}，同源海报主体person-1的人工指定裁剪；不是模型证据`}
        style={{
          width: `${100 / w}%`,
          left: 0,
          top: 0,
          transform: `translate(${-x * 100}%,${-y * 100}%)`,
        }}
      />
    </div>
  );
}
export function ResultExplorer({
  run,
  onSnapshot,
  onEdit,
}: {
  run: DemoRun;
  onSnapshot: () => void;
  onEdit: () => void;
}) {
  const [time, setTime] = useState(12);
  const [tab, setTab] = useState("events");
  const [query, setQuery] = useState("");
  const [annotations, setAnnotations] = useState(true);
  const [highlight, setHighlight] = useState("");
  const [evidenceDetail, setEvidenceDetail] = useState<DemoEvidence | null>(
    null,
  );
  const event = run.events[0];
  const visible = run.events.filter((e) => e.name.includes(query.trim()));
  const selectEvent = () => {
    setTime(event?.atSeconds ?? 0);
    setHighlight("");
    setAnnotations(true);
  };
  return (
    <main className="run-page result-page">
      <div className="run-heading">
        <h1>
          运行记录 /{" "}
          {run.snapshot.name === "区域联合告警"
            ? "区域告警"
            : run.snapshot.name}{" "}
          / 验证结果
        </h1>
        <p>
          基于版本 R{run.revision} 的脚本示例 ·{" "}
          {run.resultAvailability === "scripted"
            ? "用于展示事件与证据关联，不是实际识别结果"
            : "未提供该配置的演示结果，不等于检测到0个目标"}
        </p>
      </div>
      <div className="run-result-grid">
        <section className="panel run-card result-media-card">
          <header>
            <h2>画面与标注结果</h2>
            <div className="result-view-switch">
              <Button
                className={annotations ? "selected" : ""}
                onClick={() => setAnnotations(true)}
              >
                标注结果
              </Button>
              <Button
                className={!annotations ? "selected" : ""}
                onClick={() => setAnnotations(false)}
              >
                原始画面
              </Button>
            </div>
          </header>
          <RunMedia
            document={run.snapshot}
            time={time}
            onTime={(v) => {
              setTime(v);
              setHighlight("");
            }}
            results={!!event && time === event.atSeconds}
            highlight={highlight}
            annotations={annotations}
          />
          <div className="run-filmstrip" aria-label="模拟采样时间">
            {[0, 5, 10, 12, 15, 20, 25].map((t) => (
              <button
                key={t}
                className={time === t ? "selected" : ""}
                onClick={() => {
                  setTime(t);
                  setHighlight("");
                }}
                aria-label={`查看模拟时间${t}秒`}
                aria-pressed={time === t}
              >
                <img src={poster} alt="" />
                <span>{formatTime(t)}</span>
              </button>
            ))}
          </div>
          <h3>事件时间线（示例）</h3>
          <div className="event-timeline">
            {event ? (
              <button onClick={selectEvent}>
                <PlayCircleIcon size={23} />
                <span>{formatTime(event.atSeconds)}</span>
                <div>
                  <strong>
                    {event.name} <small>示例</small>
                  </strong>
                  <p>事件与本次快照关联；不是实时识别判断。</p>
                </div>
              </button>
            ) : (
              <p>没有可展示的脚本事件；请勿解读为业务条件不成立。</p>
            )}
          </div>
        </section>
        <section className="panel run-card result-details">
          <div className="result-tabs" role="tablist" aria-label="结果详情">
            {[
              ["events", "事件与结论"],
              ["conditions", "条件过程"],
              ["execution", "执行明细"],
            ].map(([id, label]) => (
              <button
                key={id}
                role="tab"
                id={`tab-${id}`}
                aria-controls="result-tab-content"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <div
            role="tabpanel"
            id="result-tab-content"
            aria-labelledby={`tab-${tab}`}
          >
            {tab === "events" && (
              <>
                <div className="event-list-heading">
                  <h3>
                    事件列表 <small>{run.events.length}条</small>
                  </h3>
                  <input
                    type="search"
                    aria-label="筛选事件"
                    placeholder="筛选事件"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                {visible.map((e) => (
                  <button
                    className="event-result selected"
                    key={e.id}
                    onClick={selectEvent}
                    aria-label={`定位事件${e.name}`}
                  >
                    <PlayCircleIcon size={31} weight="fill" />
                    <div>
                      <strong>
                        {e.name} · {formatTime(e.atSeconds)} <small>示例</small>
                      </strong>
                      <p>区域1属性条件与区域2数量条件同时满足。</p>
                    </div>
                  </button>
                ))}
                {!visible.length && (
                  <div className="empty-run">
                    <InfoIcon size={30} />
                    <strong>
                      {query ? "没有匹配的示例事件" : "未提供该配置的演示结果"}
                    </strong>
                    <p>
                      {query
                        ? "修改筛选词，不会删除原事件。"
                        : "当前只演示状态流程，不对新规则生成或推断业务结果。"}
                    </p>
                  </div>
                )}
                {event && (
                  <>
                    <h3 className="why-title">为什么成立（固定脚本说明）</h3>
                    <div className="result-branch orange">
                      <h3>
                        区域1 人员属性条件{" "}
                        <span className="satisfied">已满足 · 示例</span>
                      </h3>
                      <p>同一主体person-1 · 不是两个人分别满足</p>
                      {event.evidence.map((e) => (
                        <button
                          className={`result-condition ${highlight === e.id ? "highlighted" : ""}`}
                          key={e.id}
                          onClick={() => {
                            setTime(event.atSeconds);
                            setHighlight(e.id);
                            setAnnotations(true);
                          }}
                        >
                          {run.snapshot.conditions.find(
                            (c) => c.id === e.conditionId,
                          )?.part === "upper" ? (
                            <TShirtIcon
                              size={22}
                              weight="fill"
                              color="#ef4444"
                            />
                          ) : (
                            <PantsIcon
                              size={22}
                              weight="fill"
                              color="#4f46e5"
                            />
                          )}
                          {e.label}
                          <span className="satisfied">已满足</span>
                        </button>
                      ))}
                    </div>
                    <div className="result-branch teal">
                      <h3>
                        区域2 人数条件{" "}
                        <span className="satisfied">已满足 · 人数2</span>
                      </h3>
                      <p>固定脚本：位于区域2的人数达到阈值</p>
                      <div className="result-condition">
                        <UsersIcon size={22} />
                        人数 ≥ 2<span className="satisfied">示例人数2</span>
                      </div>
                    </div>
                    <div className="result-and">
                      <span>AND</span>
                      <strong>两个分支同时满足</strong>
                      <span className="satisfied">示例</span>
                    </div>
                  </>
                )}
              </>
            )}
            {tab === "conditions" && (
              <div className="snapshot-conditions">
                <h3>本次快照 R{run.revision} 的条件</h3>
                {run.snapshot.conditions.map((c) => (
                  <div key={c.id}>
                    <strong>{c.label}</strong>
                    <p>
                      {c.minimumFraction !== undefined
                        ? `颜色至少占${c.minimumFraction * 100}% · ${c.semanticQuery}`
                        : c.value !== undefined
                          ? `阈值${c.value}`
                          : "区域来源已保存于本次快照"}
                    </p>
                  </div>
                ))}
                <p className="field-explanation">
                  这里只展示快照和脚本解释；没有运行模型测色或通用判断。
                </p>
              </div>
            )}
            {tab === "execution" && (
              <div className="snapshot-conditions">
                <h3>执行明细（前端模拟）</h3>
                <p>运行标识：{run.id}</p>
                <p>
                  快照：R{run.revision} · 采样点：{run.sampleTimes.length}个
                </p>
                <p>实际模型请求0次；没有视频解码、检测、去重或跟踪。</p>
                <p>
                  结果来源：
                  {run.resultAvailability === "scripted"
                    ? "显式固定脚本"
                    : "未提供对应脚本"}
                </p>
                <p>证据比例35%/42%为脚本值，不是图像测量。</p>
              </div>
            )}
          </div>
          <div className="result-snapshot">
            <FileTextIcon size={25} />
            <div>
              <strong>查看本次条件配置</strong>
              <p>只读快照 R{run.revision}，与当前草稿分开</p>
            </div>
            <Button onClick={onSnapshot}>查看快照</Button>
            <Button onClick={onEdit}>去编辑</Button>
          </div>
          {event && (
            <div className="evidence-section">
              <header>
                <h3>证据 {event.evidence.length}项</h3>
                <small>人工指定同源裁剪 · 非模型输出</small>
              </header>
              <div className="evidence-cards">
                {event.evidence.map((e) => (
                  <button
                    key={e.id}
                    className={highlight === e.id ? "selected" : ""}
                    onClick={() => {
                      setTime(12);
                      setHighlight(e.id);
                      setAnnotations(true);
                      setEvidenceDetail(e);
                    }}
                    aria-label={`查看证据${e.label}`}
                  >
                    <EvidenceCrop evidence={e} />
                    <strong>{e.label}</strong>
                    <small>00:12 · 同一主体person-1</small>
                  </button>
                ))}
              </div>
            </div>
          )}
          <p className="result-disclaimer">
            <InfoIcon size={18} />
            以上为脚本示例，非实际业务验证数据。
          </p>
          <div className="result-downloads">
            <strong>下载结果</strong>
            <Button
              icon={DownloadSimpleIcon}
              onClick={() => downloadJson(run, `${run.id}-demo-events.json`)}
            >
              事件记录JSON
            </Button>
            <Button
              icon={ArrowSquareOutIcon}
              disabled={!event}
              onClick={() =>
                downloadJson(
                  {
                    demo: true,
                    runId: run.id,
                    revision: run.revision,
                    source: poster,
                    evidence: event?.evidence,
                  },
                  `${run.id}-evidence-manifest.json`,
                )
              }
            >
              证据清单
            </Button>
          </div>
          <small>没有真实视频，不提供标注视频下载。</small>
        </section>
      </div>
      {evidenceDetail && (
        <Modal
          title={`${evidenceDetail.label} · 示例证据`}
          onClose={() => setEvidenceDetail(null)}
        >
          <EvidenceCrop evidence={evidenceDetail} />
          <p>00:12 · 主体person-1 · 条件{evidenceDetail.conditionId}</p>
          <p>模型语义短语：{evidenceDetail.semanticQuery}</p>
          <p>
            脚本比例{Math.round(evidenceDetail.fraction * 100)}%（非测量），阈值
            {(run.snapshot.conditions.find(
              (c) => c.id === evidenceDetail.conditionId,
            )?.minimumFraction ?? 0) * 100}
            %。
          </p>
          <p>裁剪来自同一张海报，人工确定；没有声称通过模型识别。</p>
        </Modal>
      )}
    </main>
  );
}
