import { useEffect, useImperativeHandle, useState, type Ref } from "react";
import { Arrow, Circle, Group, Layer, Line, Stage } from "react-konva";
import {
  ArrowUUpLeftIcon,
  ArrowUUpRightIcon,
  ArrowsOutIcon,
  CaretDownIcon,
  CheckCircleIcon,
  CursorIcon,
  FileTextIcon,
  InfoIcon,
  PauseIcon,
  PlayIcon,
  SelectionIcon,
  SpeakerHighIcon,
  PolygonIcon,
  ArrowBendUpRightIcon,
} from "@phosphor-icons/react";
import { Button, IconButton } from "./ui";
import { useElementSize } from "../hooks/useElementSize";
import type { Point, Region, SkillDocument } from "../data/document";

export type SceneEditGuard = {
  isDirty: () => boolean;
  save: (base?: SkillDocument) => boolean;
  discard: () => void;
  start: (tool: string) => void;
};
type Props = {
  ref?: Ref<SceneEditGuard>;
  document: SkillDocument;
  selectedRegion: string;
  onSelect: (id: string) => void;
  onCommit: (doc: SkillDocument) => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onNotice: (text: string) => void;
  screenshotMode: boolean;
  onRequest: (action: () => void) => void;
  annotation?: boolean;
};
export function SceneViewport({
  ref,
  document,
  selectedRegion,
  onSelect,
  onCommit,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onNotice,
  screenshotMode,
  onRequest,
  annotation = false,
}: Props) {
  const [mediaRef, size] = useElementSize<HTMLDivElement>();
  const [drawing, setDrawing] = useState(false);
  const [drawn, setDrawn] = useState<Point[]>([]);
  const [tool, setTool] = useState("polygon");
  const [time, setTime] = useState(12);
  const [playing, setPlaying] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const region = document.regions.find((r) => r.id === selectedRegion);
  const width = size.width;
  const height = size.height;
  const mediaRatio = 1448 / 1086;
  const containedWidth = Math.min(width, height * mediaRatio);
  const containedHeight = containedWidth / mediaRatio;
  const offsetX = (width - containedWidth) / 2;
  const offsetY = (height - containedHeight) / 2;
  const saveDrawing = (base?: SkillDocument): boolean => {
    if (drawn.length < (tool === "direction" ? 2 : 3)) {
      onNotice(
        tool === "direction"
          ? "请选择方向起点与终点。"
          : "至少选择3个点后，才能保存多边形区域。",
      );
      return false;
    }
    const changed = {
      ...(base ?? document),
      regions: (base ?? document).regions.map((r) =>
        r.id === selectedRegion
          ? { ...r, type: tool, points: drawn, saved: true }
          : r,
      ),
    };
    onCommit(changed);
    setDrawing(false);
    setDrawn([]);
    onNotice(`${region?.name}已保存到草稿，尚未应用。`);
    return true;
  };
  useImperativeHandle(ref, () => ({
    isDirty: () => drawing && drawn.length > 0,
    save: saveDrawing,
    discard: () => {
      setDrawing(false);
      setDrawn([]);
    },
    start: (nextTool) => {
      setDrawing(true);
      setTool(nextTool);
      setDrawn([]);
    },
  }));
  useEffect(() => {
    if (!playing || screenshotMode) return;
    const timer = setInterval(
      () =>
        setTime((t) => {
          if (t >= 30) {
            setPlaying(false);
            return 30;
          }
          return t + 1;
        }),
      1000,
    );
    return () => clearInterval(timer);
  }, [playing, screenshotMode]);
  const updatePoint = (target: Region, index: number, point: Point) => {
    onCommit({
      ...document,
      regions: document.regions.map((r) =>
        r.id === target.id
          ? {
              ...r,
              points: r.points.map((p, i) => (i === index ? point : p)),
              saved: true,
            }
          : r,
      ),
    });
  };
  return (
    <section
      className={`scene-panel panel ${annotation ? "annotation-mode" : ""} ${zoomed ? "media-expanded" : ""}`}
      aria-label="场景预览"
    >
      <header className="panel-header">
        <h2>{annotation ? "画面标注" : "场景预览"}</h2>
        {!annotation && (
          <span className="media-pill">
            <PlayIcon size={14} />
            {drawing ? "区域编辑中" : "海报 · 模拟时间轴"}
          </span>
        )}
        <div className="scene-tools">
          <Button
            icon={CursorIcon}
            variant={!drawing ? "primary" : "neutral"}
            onClick={() =>
              onRequest(() => {
                setDrawing(false);
                setDrawn([]);
              })
            }
          >
            选择
          </Button>
          <Button
            icon={SelectionIcon}
            variant={drawing ? "primary" : "neutral"}
            onClick={() =>
              onRequest(() => {
                setDrawing(true);
                setTool("polygon");
                setDrawn([]);
              })
            }
          >
            {annotation ? "多边形" : "绘制区域"}
          </Button>
          {annotation && (
            <>
              <Button
                icon={SelectionIcon}
                variant={
                  drawing && tool === "rectangle" ? "primary" : "neutral"
                }
                onClick={() =>
                  onRequest(() => {
                    setDrawing(true);
                    setTool("rectangle");
                    setDrawn([]);
                  })
                }
              >
                矩形
              </Button>
              <Button
                icon={ArrowBendUpRightIcon}
                variant={
                  drawing && tool === "direction" ? "primary" : "neutral"
                }
                disabled={
                  !!document.conditions.find((c) => c.region === selectedRegion)
                }
                title="已被区域条件引用的资源不能改为方向"
                onClick={() =>
                  onRequest(() => {
                    setDrawing(true);
                    setTool("direction");
                    setDrawn([]);
                  })
                }
              >
                方向参考
              </Button>
            </>
          )}
          <button
            className="text-tool"
            title={canUndo ? "撤销上次修改" : "暂无可撤销修改"}
            onClick={() => onRequest(onUndo)}
            disabled={!canUndo}
          >
            <ArrowUUpLeftIcon size={21} />
            撤销
          </button>
          {canRedo && (
            <IconButton
              icon={ArrowUUpRightIcon}
              label="重做"
              onClick={() => onRequest(onRedo)}
            />
          )}
        </div>
      </header>
      <div className="scene-body">
        <div
          ref={mediaRef}
          className={`scene-media ${drawing ? "drawing" : ""}`}
          data-testid="scene-media"
        >
          <img
            className="construction-image"
            src="/assets/media/construction-clean.png"
            alt="俯视施工场景：左侧红上衣工人，中上蓝衣工人，右侧两名反光背心工人；生成演示海报"
          />
          {width > 0 && (
            <div className="annotation-layer" aria-hidden="true">
              <Stage
                width={width}
                height={height}
                onMouseDown={(event) => {
                  if (!drawing) return;
                  const position = event.target
                    .getStage()
                    ?.getPointerPosition();
                  if (
                    position &&
                    position.x >= offsetX &&
                    position.x <= offsetX + containedWidth &&
                    position.y >= offsetY &&
                    position.y <= offsetY + containedHeight
                  )
                    setDrawn((p) => {
                      const point: Point = [
                        (position.x - offsetX) / containedWidth,
                        (position.y - offsetY) / containedHeight,
                      ];
                      if (tool === "rectangle" && p.length === 1)
                        return [
                          p[0],
                          [point[0], p[0][1]],
                          point,
                          [p[0][0], point[1]],
                        ];
                      if (
                        (tool === "rectangle" && p.length >= 4) ||
                        (tool === "direction" && p.length >= 2)
                      )
                        return [point];
                      return [...p, point];
                    });
                }}
              >
                <Layer>
                  {document.regions.map((r) => (
                    <Group
                      key={r.id}
                      onClick={() => !drawing && onSelect(r.id)}
                    >
                      {r.type === "direction" ? (
                        <Arrow
                          points={r.points.flatMap(([x, y]) => [
                            offsetX + x * containedWidth,
                            offsetY + y * containedHeight,
                          ])}
                          stroke="#4F46E5"
                          fill="#4F46E5"
                          strokeWidth={3}
                        />
                      ) : (
                        <Line
                          points={r.points.flatMap(([x, y]) => [
                            offsetX + x * containedWidth,
                            offsetY + y * containedHeight,
                          ])}
                          closed
                          stroke={
                            r.colorIdentity === "orange" ? "#F59E0B" : "#14B8A6"
                          }
                          strokeWidth={3}
                          fill={
                            r.colorIdentity === "orange"
                              ? "rgba(245,158,11,.22)"
                              : "rgba(20,184,166,.23)"
                          }
                        />
                      )}
                      {r.points.map(([x, y], i) => (
                        <Circle
                          key={`${r.id}-${i}`}
                          x={offsetX + x * containedWidth}
                          y={offsetY + y * containedHeight}
                          radius={6.5}
                          fill="#fff"
                          stroke={
                            r.colorIdentity === "orange" ? "#F59E0B" : "#14B8A6"
                          }
                          strokeWidth={2.5}
                          draggable={!drawing && r.id === selectedRegion}
                          onDragEnd={(event) => {
                            const updated: Point = [
                              Math.max(
                                0,
                                Math.min(
                                  1,
                                  (event.target.x() - offsetX) / containedWidth,
                                ),
                              ),
                              Math.max(
                                0,
                                Math.min(
                                  1,
                                  (event.target.y() - offsetY) /
                                    containedHeight,
                                ),
                              ),
                            ];
                            setTool(r.type);
                            setDrawing(true);
                            setDrawn(
                              r.points.map((p, index) =>
                                index === i ? updated : p,
                              ),
                            );
                          }}
                        />
                      ))}
                    </Group>
                  ))}
                  {drawn.length > 0 && (
                    <Group>
                      <Line
                        points={drawn.flatMap(([x, y]) => [
                          offsetX + x * containedWidth,
                          offsetY + y * containedHeight,
                        ])}
                        stroke="#4F46E5"
                        strokeWidth={3}
                        closed={drawn.length > 2}
                        fill="rgba(79,70,229,.13)"
                      />
                      {drawn.map(([x, y], i) => (
                        <Circle
                          key={i}
                          x={offsetX + x * containedWidth}
                          y={offsetY + y * containedHeight}
                          radius={5}
                          fill="#4F46E5"
                          stroke="#fff"
                          strokeWidth={2}
                        />
                      ))}
                    </Group>
                  )}
                </Layer>
              </Stage>
            </div>
          )}
          {document.regions.map((r) => (
            <button
              key={r.id}
              className={`region-tag ${r.colorIdentity} ${r.id === selectedRegion ? "selected" : ""}`}
              style={{
                left:
                  annotation && r.points.length
                    ? offsetX +
                      (r.points.reduce((a, p) => a + p[0], 0) /
                        r.points.length) *
                        containedWidth
                    : `${(r.colorIdentity === "orange" ? 0.155 : 0.655) * 100}%`,
                top:
                  annotation && r.points.length
                    ? Math.max(
                        2,
                        offsetY +
                          Math.min(...r.points.map((p) => p[1])) *
                            containedHeight -
                          36,
                      )
                    : "31.6%",
              }}
              onClick={() => onSelect(r.id)}
              aria-pressed={selectedRegion === r.id}
              aria-label={`选择${r.name}`}
            >
              {selectedRegion === r.id && (
                <CheckCircleIcon size={13} weight="bold" />
              )}
              {r.name}
            </button>
          ))}
          {drawing && (
            <div className="draw-helper">
              <span>
                {tool === "rectangle"
                  ? "点击两个对角点"
                  : tool === "direction"
                    ? "点击起点和终点"
                    : "依次点击画面"}
                绘制「{region?.name}」 · 已选{drawn.length}点
              </span>
              <Button variant="primary" onClick={() => saveDrawing()}>
                保存区域
              </Button>
              <button
                onClick={() =>
                  onRequest(() => {
                    setDrawing(false);
                    setDrawn([]);
                  })
                }
              >
                取消
              </button>
            </div>
          )}
        </div>
        <div className="playback">
          <IconButton
            label={playing ? "停止模拟播放" : "模拟播放时间轴"}
            icon={playing ? PauseIcon : PlayIcon}
            onClick={() => {
              if (screenshotMode) {
                onNotice(
                  "截图用例固定时间；可拖动模拟时间轴。普通演示页面可播放模拟时钟。",
                );
                return;
              }
              setPlaying((p) => !p);
              onNotice("当前是海报演示：可拖动模拟时间轴，不会播放真实视频。");
            }}
          />
          <span className="timecode">
            00:{String(time).padStart(2, "0")} / 00:30
          </span>
          <span className="timeline-track">
            <progress value={time} max={30} aria-hidden="true" />
            <input
              type="range"
              min="0"
              max="30"
              step="1"
              value={time}
              aria-label="模拟时间轴"
              onChange={(e) => {
                setTime(Number(e.target.value));
                setPlaying(false);
              }}
            />
          </span>
          <IconButton
            label="声音不可用（海报模式）"
            icon={SpeakerHighIcon}
            onClick={() => onNotice("海报没有音轨，未提供真实视频。")}
          />
          <IconButton
            label={zoomed ? "退出放大画面" : "放大画面"}
            icon={ArrowsOutIcon}
            onClick={() => setZoomed((p) => !p)}
          />
        </div>
        <div
          className="filmstrip"
          aria-label="模拟帧位置（均来自同一海报，不是真实视频帧）"
        >
          {[0, 4, 8, 12, 16, 20, 24, 28].map((t) => (
            <button
              key={t}
              className={time === t ? "current" : ""}
              aria-label={`查看模拟时间${t}秒`}
              aria-pressed={time === t}
              onClick={() => setTime(t)}
            >
              <img
                src="/assets/media/construction-clean.png"
                alt="同源海报缩略图"
                loading="eager"
              />
              <span>{String(t).padStart(2, "0")}s</span>
            </button>
          ))}
        </div>
        {!annotation && (
          <>
            <div className="selection-message" aria-live="polite">
              <span className={`status-dot ${region?.colorIdentity}`} />
              <strong>
                已选择{region?.name} ·{" "}
                <span>
                  已定位到分支 {region?.colorIdentity === "orange" ? "A" : "B"}
                </span>
              </strong>
              <span className="selection-hint">
                <InfoIcon size={18} />
                点击画面区域，可定位对应规则
              </span>
            </div>
            <button
              className="evidence-toggle"
              aria-expanded={expanded}
              onClick={() => setExpanded((p) => !p)}
            >
              <FileTextIcon size={22} />
              <span>
                结果与证据 · <small>运行后查看</small>
              </span>
              <CaretDownIcon size={18} className={expanded ? "rotate" : ""} />
            </button>
            {expanded && (
              <div className="evidence-empty">
                <InfoIcon size={18} />
                本页尚未运行识别。后续模拟结果会与运行快照关联，不会用草稿推算真实检测结果。
              </div>
            )}
          </>
        )}
        {annotation && (
          <p className="annotation-footnote">
            <InfoIcon size={18} />
            标注跟随原始画面，不受缩放或切片影响。海报与时间轴均为演示。
          </p>
        )}
      </div>
    </section>
  );
}
