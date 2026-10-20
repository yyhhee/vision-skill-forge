import { useState } from "react";
import { Layer, Line, Rect, Stage } from "react-konva";
import { ArrowsOutIcon } from "@phosphor-icons/react";
import { useElementSize } from "../../hooks/useElementSize";
import type { SkillDocument } from "../../data/document";
import { formatTime, poster } from "../../data/runs";
import { IconButton, Modal } from "../ui";

export function RunMedia({
  document,
  time,
  onTime,
  results = false,
  highlight = "",
  annotations = true,
  controls = true,
}: {
  document: SkillDocument;
  time: number;
  onTime?: (time: number) => void;
  results?: boolean;
  highlight?: string;
  annotations?: boolean;
  controls?: boolean;
}) {
  const [ref, size] = useElementSize<HTMLDivElement>();
  const [expanded, setExpanded] = useState(false);
  const width = Math.min(size.width, (size.height * 4) / 3),
    height = width * 0.75;
  const offsetX = (size.width - width) / 2,
    offsetY = (size.height - height) / 2;
  return (
    <>
      <div
        className="run-media"
        ref={ref}
        data-testid="run-media"
        data-highlight={highlight}
      >
        <img
          src={poster}
          alt="施工场景海报；所有时间点使用同一张图片，不是真实视频帧"
        />
        {annotations && width > 0 && (
          <>
            <Stage
              width={size.width}
              height={size.height}
              listening={false}
              aria-hidden="true"
            >
              <Layer>
                {document.regions
                  .filter((r) => r.saved)
                  .map((r) => (
                    <Line
                      key={r.id}
                      points={r.points.flatMap(([x, y]) => [
                        offsetX + x * width,
                        offsetY + y * height,
                      ])}
                      closed
                      stroke={
                        r.colorIdentity === "orange" ? "#ff8a16" : "#14b8c4"
                      }
                      fill={
                        r.colorIdentity === "orange" ? "#ff8a1633" : "#14b8c433"
                      }
                      strokeWidth={3}
                    />
                  ))}
                {results && (
                  <>
                    <Rect
                      x={offsetX + width * 0.17}
                      y={offsetY + height * 0.435}
                      width={width * 0.09}
                      height={height * 0.255}
                      stroke="#f43f5e"
                      strokeWidth={highlight ? 4 : 2}
                    />
                    <Rect
                      x={offsetX + width * 0.756}
                      y={offsetY + height * 0.41}
                      width={width * 0.07}
                      height={height * 0.24}
                      stroke="#0e91a9"
                      strokeWidth={2}
                    />
                    <Rect
                      x={offsetX + width * 0.87}
                      y={offsetY + height * 0.4}
                      width={width * 0.085}
                      height={height * 0.25}
                      stroke="#0e91a9"
                      strokeWidth={2}
                    />
                  </>
                )}
              </Layer>
            </Stage>
            {document.regions
              .filter((r) => r.saved && r.points.length)
              .map((r) => (
                <span
                  key={r.id}
                  className={`run-region-label ${r.colorIdentity}`}
                  style={{
                    left: offsetX + r.points[0][0] * width,
                    top: offsetY + r.points[0][1] * height - 30,
                  }}
                >
                  {r.name}
                </span>
              ))}
            {results && (
              <span
                className="run-person-label"
                style={{
                  left: offsetX + width * 0.17,
                  top: offsetY + height * 0.4,
                }}
              >
                符合属性的人员 · 示例
              </span>
            )}
          </>
        )}
        <span className="poster-notice">海报 · 模拟时间轴</span>
      </div>
      {controls && (
        <div className="run-media-controls">
          <span>{formatTime(time)} / 00:30</span>
          <input
            type="range"
            aria-label="结果模拟时间轴"
            min="0"
            max="30"
            step="1"
            value={time}
            disabled={!onTime}
            onChange={(e) => onTime?.(Number(e.target.value))}
          />
          <IconButton
            icon={ArrowsOutIcon}
            label="放大查看海报"
            onClick={() => setExpanded(true)}
          />
        </div>
      )}
      {expanded && (
        <Modal
          title="施工场景海报（非视频帧）"
          onClose={() => setExpanded(false)}
        >
          <img
            className="expanded-poster"
            src={poster}
            alt="干净原始施工海报"
          />
        </Modal>
      )}
    </>
  );
}
