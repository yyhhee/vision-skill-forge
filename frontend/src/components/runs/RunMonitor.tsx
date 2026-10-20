import {
  CheckCircleIcon,
  CubeIcon,
  FileTextIcon,
  ImageIcon,
} from "@phosphor-icons/react";
import { formatTime, type DemoRun } from "../../data/runs";
import { Button } from "../ui";
import { RunMedia } from "./RunMedia";

const statusNames = {
  running: "正在模拟验证",
  completed: "模拟验证完成",
  cancelled: "本次模拟已取消",
  failed: "本次模拟失败",
};
export function RunMonitor({
  run,
  playing,
  frozen = false,
  onPlaying,
  onAdvance,
  onResults,
  onFail,
}: {
  run: DemoRun;
  playing: boolean;
  frozen?: boolean;
  onPlaying: (p: boolean) => void;
  onAdvance: () => void;
  onResults: () => void;
  onFail: () => void;
}) {
  const time = run.sampleTimes[run.completedFrames] ?? run.settings.endSeconds;
  const percent = Math.round(
    (run.completedFrames / run.sampleTimes.length) * 100,
  );
  const stage =
    run.status === "completed" ? 4 : run.completedFrames >= 24 ? 2 : 1;
  const categories = [
    ...new Set([
      ...run.snapshot.entitySources.map((s) => s.category),
      ...run.snapshot.conditions.map((c) => c.semanticQuery).filter(Boolean),
    ]),
  ];
  return (
    <main className="run-page monitor-page">
      <div className="run-heading">
        <h1>{statusNames[run.status]}</h1>
        <p>
          使用 R{run.revision} <span>｜</span> 施工场景海报 <span>｜</span>{" "}
          纯前端脚本演示
        </p>
        <p>基于本次快照：{run.snapshot.instruction}</p>
      </div>
      <div className="run-monitor-grid">
        <div className="monitor-left">
          <section className="panel run-card">
            <header>
              <h2>当前处理画面（示意）</h2>
              {run.status === "running" && (
                <div
                  className="simulation-controls"
                  title="离开此页会暂停，不会另建任务。"
                >
                  <Button
                    disabled={frozen}
                    title={
                      frozen
                        ? "截图用例不自动推进，可手动推进采样点。"
                        : undefined
                    }
                    onClick={() => onPlaying(!playing)}
                  >
                    {playing ? "暂停模拟" : "继续模拟"}
                  </Button>
                  <Button disabled={playing} onClick={onAdvance}>
                    推进一个采样点
                  </Button>
                </div>
              )}
            </header>
            <RunMedia document={run.snapshot} time={time} />
            <div className="frame-progress">
              <progress
                aria-label="模拟采样进度"
                max={run.sampleTimes.length}
                value={run.completedFrames}
              />
              <span>
                已处理 {run.completedFrames} / {run.sampleTimes.length}{" "}
                个采样帧（{percent}%）
              </span>
            </div>
            {run.status === "completed" && (
              <Button variant="primary" onClick={onResults}>
                查看结果与证据
              </Button>
            )}
            {run.status === "cancelled" && (
              <div className="run-notice">
                已停止在{run.completedFrames}
                帧；取消不等于完成，未产生业务结果。
              </div>
            )}
            {run.status === "failed" && (
              <div className="run-error" role="alert">
                {run.error}
              </div>
            )}
          </section>
          <section className="panel run-card run-log">
            <h2>运行消息</h2>
            <ul>
              <li>
                <span>准备</span>已锁定运行版本R{run.revision}，不是当前草稿。
              </li>
              <li>
                <span>素材</span>已读取本地海报；30秒时间轴为模拟数据。
              </li>
              <li>
                <span>进度</span>
                {run.status === "running"
                  ? `下一采样点 ${formatTime(time)}`
                  : statusNames[run.status]}{" "}
                · 已处理{run.completedFrames}帧。
              </li>
            </ul>
            <details>
              <summary>专业执行明细 · 点击展开</summary>
              <p>模型请求：0；没有模型检测、测色、跟踪、切片或去重执行。</p>
              <p>一次多类别请求的配置短语：{categories.join(", ")}</p>
              <p>运行标识：{run.id}</p>
              <Button
                variant="danger"
                disabled={run.status !== "running"}
                onClick={onFail}
              >
                触发模拟失败
              </Button>
            </details>
          </section>
        </div>
        <div className="monitor-right">
          <section className="panel run-card">
            <h2>运行进度</h2>
            <ol className="run-stages">
              {[
                "素材准备",
                "多类别检测（模拟）",
                "条件与编排判断（模拟）",
                "生成标注与证据（脚本）",
              ].map((label, index) => (
                <li
                  key={label}
                  className={
                    index < stage
                      ? "stage-done"
                      : index === stage
                        ? "stage-current"
                        : ""
                  }
                >
                  <span className="stage-circle">
                    {index < stage ? <CheckCircleIcon size={24} /> : index + 1}
                  </span>
                  <div>
                    <strong>{label}</strong>
                    <p>
                      {
                        [
                          "加载本地海报与快照，不解析真实视频",
                          "所有类别属于同一演示请求计划；未实际调用模型",
                          "固定脚本演示，不执行通用条件推理",
                          "保留本次快照、事件与证据关联",
                        ][index]
                      }
                    </p>
                  </div>
                  <small>
                    {run.status === "cancelled"
                      ? "已取消"
                      : run.status === "failed"
                        ? "已中止"
                        : index < stage
                          ? "已完成"
                          : index === stage
                            ? "处理中"
                            : "等待中"}
                  </small>
                </li>
              ))}
            </ol>
            <h3>当前使用的视觉模型</h3>
            <div className="model-summary">
              <CubeIcon size={34} />
              <div>
                <strong>视觉演示适配器</strong>
                <p>未连接模型 · 实际请求0次</p>
              </div>
            </div>
            <div className="task-summary">
              <FileTextIcon size={24} />
              <div>
                <strong>本次任务要点</strong>
                <ul>
                  {run.snapshot.branches.map((b) => (
                    <li key={b.id}>
                      {b.name}：
                      {b.logic.members
                        .map(
                          (id) =>
                            run.snapshot.conditions.find((c) => c.id === id)
                              ?.label ?? id,
                        )
                        .join("、")}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </section>
          <section className="panel run-card monitor-results">
            <h2>结果与证据</h2>
            <div className="empty-run">
              <ImageIcon size={34} />
              <strong>
                {run.status === "completed"
                  ? "模拟结果已就绪"
                  : "任务结束后再查看结果状态"}
              </strong>
              <p>
                只有匹配固定脚本的配置才提供示例事件，不能证明真实识别效果。
              </p>
              {run.status === "completed" && (
                <Button onClick={onResults}>打开结果</Button>
              )}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
