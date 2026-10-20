import {
  BellIcon,
  ImagesIcon,
  PlayIcon,
  DownloadSimpleIcon,
  FileTextIcon,
  FolderIcon,
  InfoIcon,
  ImageIcon,
  CaretRightIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Button, IconButton } from "../ui";
import {
  historyDate,
  historyStatusNames,
  type HistoryRow,
} from "../../data/runHistory";
export function RunHistoryDetail({
  row,
  close,
  view,
  exportRow,
}: {
  row: HistoryRow;
  close: () => void;
  view: () => void;
  exportRow: () => void;
}) {
  const date = historyDate(row.createdAt);
  return (
    <aside className="panel history-detail" aria-label="运行结果详情">
      <header>
        <h2>运行结果详情</h2>
        <IconButton label="关闭运行详情" icon={XIcon} onClick={close} />
      </header>
      {row.thumbnail ? (
        <img
          className="history-detail-image"
          src={row.thumbnail}
          alt={`${row.name}的示例海报，非真实视频帧`}
        />
      ) : (
        <div className="history-no-media">
          <ImageIcon size={36} aria-hidden="true" />
          <span>素材未接入，不替换成示例图片</span>
        </div>
      )}
      <div className="history-detail-title">
        <h3>{row.name}</h3>
        <span className={`history-state ${row.status}`}>
          {historyStatusNames[row.status]}
        </span>
      </div>
      <dl>
        <dt>素材</dt>
        <dd>{row.mediaLabel}</dd>
        <dt>使用版本</dt>
        <dd>{row.revision ? `R${row.revision}` : "参考摘要 · 未提供快照"}</dd>
        <dt>开始时间</dt>
        <dd>
          {date.day} {date.time}（北京时间）
        </dd>
      </dl>
      <div className="history-counts">
        <button onClick={view}>
          <BellIcon size={26} aria-hidden="true" />
          <span>
            事件{row.run ? "示例" : "摘要"}{" "}
            {row.eventCount === null ? "未提供" : `${row.eventCount} 条`}
          </span>
          <CaretRightIcon size={19} aria-hidden="true" />
        </button>
        <button onClick={view}>
          <ImagesIcon size={26} aria-hidden="true" />
          <span>
            证据示例{" "}
            {row.evidenceCount === null ? "未提供" : `${row.evidenceCount} 项`}
          </span>
          <CaretRightIcon size={19} aria-hidden="true" />
        </button>
      </div>
      <section className="history-related">
        <h4>相关操作</h4>
        <Button icon={PlayIcon} variant="primary" onClick={view}>
          {row.status === "running"
            ? "查看模拟进度"
            : row.status === "failed"
              ? "查看失败原因"
              : "查看结果"}
        </Button>
        <Button
          icon={DownloadSimpleIcon}
          disabled
          title="未接入真实视频，不能下载标注视频"
        >
          下载标注视频（未接入）
        </Button>
        <Button icon={FileTextIcon} onClick={exportRow}>
          {row.run ? "导出运行记录 JSON" : "导出参考摘要 JSON"}
        </Button>
        <Button
          icon={FolderIcon}
          disabled
          title="没有真实证据文件，不提供证据包下载"
        >
          证据包（未提供）
        </Button>
      </section>
      {!row.run && (
        <p className="history-summary-note">
          此条仅有参考摘要，未提供完整配置与结果详情；不会借用其它运行的结果。
        </p>
      )}
      {row.run?.status === "running" && (
        <p className="history-summary-note">
          任务尚未结束，不代表正在后台推进；打开后需手动继续。
        </p>
      )}
      {row.run?.resultAvailability === "not_provided" && (
        <p className="history-summary-note">
          未提供该配置的演示结果，不等于检测到0个目标。
        </p>
      )}
      <p className="history-snapshot-note">
        <InfoIcon size={24} aria-hidden="true" />
        <span>历史结果对应当次运行版本，不随当前草稿变化。</span>
      </p>
    </aside>
  );
}
