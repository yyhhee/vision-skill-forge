import { useEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  SmoothStepEdge,
  type EdgeProps,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
  applyNodeChanges,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ArrowsOutIcon,
  BellIcon,
  InfoIcon,
  InfinityIcon,
  MapPinIcon,
  PantsIcon,
  PencilSimpleIcon,
  TShirtIcon,
  ShareNetworkIcon,
  UsersIcon,
} from "@phosphor-icons/react";
import { IconButton } from "./ui";
import { OrchestrationCanvas } from "./OrchestrationCanvas";
import {
  branchRegion,
  colorHex,
  conditionLabel,
  type Branch,
  type SkillDocument,
} from "../data/document";

type NodeData = {
  kind: string;
  document: SkillDocument;
  branch?: Branch;
  selectedRegion: string;
  onSelect: (id: string) => void;
  onEdit: (id: string, kind?: string) => void;
};
type BusinessNode = Node<NodeData, "business">;
function BusinessCard({ data }: NodeProps<BusinessNode>) {
  const { document, kind, branch, onEdit, onSelect, selectedRegion } = data;
  const sourceHandle = (
    <Handle type="source" position={Position.Bottom} isConnectable={false} />
  );
  const targetHandle = (
    <Handle type="target" position={Position.Top} isConnectable={false} />
  );
  if (kind === "detector")
    return (
      <div
        className="detector-card"
        role="button"
        tabIndex={0}
        aria-label="编辑检测人员"
        onDoubleClick={() => onEdit("persons", "detector")}
        onKeyDown={(e) => e.key === "Enter" && onEdit("persons", "detector")}
      >
        <UsersIcon size={37} weight="fill" />
        <div>
          <strong>检测人员</strong>
          <small>视频画面中的人员</small>
        </div>
        {sourceHandle}
      </div>
    );
  if (kind === "branch" && branch) {
    const regionId = branchRegion(document, branch.id);
    const region = document.regions.find((r) => r.id === regionId);
    const tone = region?.colorIdentity === "orange" ? "orange" : "teal";
    const members = branch.logic.members
      .map((id) => document.conditions.find((c) => c.id === id))
      .filter((c) => !!c);
    return (
      <div
        className={`branch-card ${tone} ${selectedRegion === regionId ? "selected" : ""}`}
        data-testid={branch.id}
      >
        <Handle
          type="target"
          position={Position.Top}
          isConnectable={false}
          style={{ left: tone === "orange" ? "45%" : "49%" }}
        />
        <header
          className="drag-handle"
          onClick={() => regionId && onSelect(regionId)}
        >
          <ShareNetworkIcon className="branch-symbol" size={34} />
          <div>
            <strong>{branch.name}</strong>
            <small>
              {region?.colorIdentity === "orange"
                ? `位于${region?.name ?? "所选区域"}且穿着指定服装的人员`
                : `位于${region?.name ?? "所选区域"}人数达到阈值`}
            </small>
          </div>
          <button
            className="nodrag icon-edit"
            aria-label={`编辑${branch.name}`}
            onClick={(event) => {
              event.stopPropagation();
              onEdit(branch.id, "branch");
            }}
          >
            <PencilSimpleIcon size={20} />
          </button>
        </header>
        <div className="branch-members">
          <div className="condition-rows">
            {members.map((condition) => {
              const IconComponent =
                condition.kind === "inside"
                  ? MapPinIcon
                  : condition.kind === "count"
                    ? UsersIcon
                    : condition.part === "lower"
                      ? PantsIcon
                      : TShirtIcon;
              const color =
                condition.kind === "visible_color" && condition.part === "upper"
                  ? colorHex[condition.color ?? "red"]
                  : "#4F46E5";
              return (
                <button
                  className="condition-row nodrag nopan"
                  key={condition.id}
                  onClick={(event) => {
                    event.stopPropagation();
                    onEdit(condition.id, "condition");
                  }}
                >
                  <IconComponent size={29} weight="fill" style={{ color }} />
                  <span>{conditionLabel(condition)}</span>
                </button>
              );
            })}
          </div>
          <span className="logic-bracket" aria-hidden="true" />
          <button
            className="logic-badge nodrag"
            aria-label={`修改${branch.name}逻辑组合`}
            onClick={(event) => {
              event.stopPropagation();
              onEdit(branch.id, "branch");
            }}
          >
            <span>
              {branch.logic.operator === "AND" ? "全部满足" : "任一满足"}
            </span>
            <span>{branch.logic.operator}</span>
          </button>
        </div>
        <Handle
          type="source"
          position={Position.Bottom}
          isConnectable={false}
          style={{ left: tone === "orange" ? "45%" : "49%" }}
        />
      </div>
    );
  }
  if (kind === "final")
    return (
      <div
        className="final-card"
        role="button"
        tabIndex={0}
        aria-label="编辑最终判定"
        onClick={() => onEdit(document.final.id, "final")}
        onKeyDown={(e) =>
          e.key === "Enter" && onEdit(document.final.id, "final")
        }
      >
        {targetHandle}
        <InfinityIcon size={43} weight="bold" />
        <div>
          <strong>
            {document.final.operator === "AND"
              ? "全部同时满足"
              : "任一分支满足"}
          </strong>
          <small>{document.final.operator}</small>
        </div>
        {sourceHandle}
      </div>
    );
  return (
    <div
      className="output-card"
      role="button"
      tabIndex={0}
      aria-label="编辑区域告警事件"
      onClick={() => onEdit(document.outputs[0].id, "output")}
      onKeyDown={(e) =>
        e.key === "Enter" && onEdit(document.outputs[0].id, "output")
      }
    >
      {targetHandle}
      <BellIcon size={43} weight="fill" />
      <div>
        <strong>{document.outputs[0].name}</strong>
        <small>触发区域告警</small>
      </div>
    </div>
  );
}
const nodeTypes = { business: BusinessCard };
function RoundedDependency(props: EdgeProps) {
  return (
    <SmoothStepEdge {...props} pathOptions={{ borderRadius: 28, offset: 2 }} />
  );
}
const edgeTypes = { dependency: RoundedDependency };
const edgeDefaults = { type: "dependency", style: { strokeWidth: 2.2 } };
export function RuleCanvas({
  document,
  selectedRegion,
  onSelect,
  onEdit,
  onAction,
  outputMode = false,
}: {
  document: SkillDocument;
  selectedRegion: string;
  onSelect: (id: string) => void;
  onEdit: (id: string, kind?: string) => void;
  onAction?: (action: string) => void;
  outputMode?: boolean;
}) {
  const [instance, setInstance] = useState<ReactFlowInstance<
    BusinessNode,
    Edge
  > | null>(null);
  const [positions, setPositions] = useState<
    Record<string, { x: number; y: number }>
  >({});
  const nodes = useMemo<BusinessNode[]>(
    () =>
      [
        {
          id: "persons",
          kind: "detector",
          x: 185,
          y: 27,
          width: 246,
          height: 70,
        },
        ...document.branches.map((branch, index) => ({
          id: branch.id,
          kind: "branch",
          x: 18 + index * 315,
          y: 161,
          width: index === 0 ? 294 : 292,
          height: 224,
          branch,
        })),
        {
          id: document.final.id,
          kind: "final",
          x: 198,
          y: 443,
          width: 220,
          height: 62,
        },
        {
          id: document.outputs[0].id,
          kind: "output",
          x: 198,
          y: 554,
          width: 220,
          height: 66,
        },
      ]
        .filter((n) => !outputMode || n.kind !== "detector")
        .map((n) => ({
          id: n.id,
          type: "business",
          position:
            positions[n.id] ??
            (outputMode
              ? {
                  x:
                    n.kind === "branch"
                      ? 35 +
                        document.branches.findIndex((b) => b.id === n.id) * 357
                      : 233,
                  y: n.kind === "branch" ? 80 : n.kind === "final" ? 365 : 440,
                }
              : { x: n.x, y: n.y }),
          width: n.width,
          height: n.height,
          dragHandle: n.kind === "branch" ? ".drag-handle" : undefined,
          data: {
            kind: n.kind,
            branch: "branch" in n ? n.branch : undefined,
            document,
            selectedRegion,
            onSelect,
            onEdit,
          },
        })),
    [document, selectedRegion, onSelect, onEdit, positions, outputMode],
  );
  const edges: Edge[] = useMemo(
    () =>
      [
        ...document.branches.map((b, index) => ({
          id: `detect-${b.id}`,
          source: "persons",
          target: b.id,
          stroke: index === 0 ? "#F59E0B" : "#14B8A6",
        })),
        ...document.final.members.map((id, index) => ({
          id: `${id}-final`,
          source: id,
          target: document.final.id,
          stroke: index === 0 ? "#4F46E5" : "#14B8A6",
        })),
        {
          id: "final-out",
          source: document.outputs[0].source,
          target: document.outputs[0].id,
          stroke: "#4F46E5",
        },
      ].map((edge) => ({
        ...edgeDefaults,
        ...edge,
        style: { ...edgeDefaults.style, stroke: edge.stroke },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: edge.stroke,
          width: 12,
          height: 12,
        },
      })),
    [document],
  );
  useEffect(() => {
    instance?.setViewport({ x: 0, y: 0, zoom: 1 });
  }, [instance]);
  if (document.groups.length)
    return (
      <OrchestrationCanvas
        document={document}
        onEdit={onEdit}
        onAdd={() => onAction?.("新增组")}
      />
    );
  return (
    <section
      className={`canvas-panel panel ${outputMode ? "output-canvas" : ""}`}
      aria-label="规则画布"
    >
      <header className="panel-header">
        <h2>{outputMode ? "最终判定" : "规则画布"}</h2>
        <span className="canvas-hint">
          <InfoIcon size={18} />
          连线表示依赖，不代表先后顺序
        </span>
        {onAction && (
          <select
            aria-label="编辑工作区"
            className="canvas-editor-select"
            value=""
            onChange={(e) => onAction(e.target.value)}
          >
            <option value="">编辑…</option>
            {["条件编辑", "时间约束", "编排组", "业务输出", "检查配置"].map(
              (name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ),
            )}
          </select>
        )}
        <IconButton
          icon={ArrowsOutIcon}
          label="适配全部规则"
          onClick={() => instance?.fitView({ padding: 0.07, maxZoom: 1.2 })}
        />
      </header>
      <div className="rule-flow" data-testid="rule-flow">
        <ReactFlow<BusinessNode, Edge>
          nodes={nodes}
          edges={edges.filter(
            (edge) => !outputMode || edge.source !== "persons",
          )}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onInit={setInstance}
          defaultViewport={{ x: 0, y: 0, zoom: 1 }}
          minZoom={0.25}
          maxZoom={2}
          nodesConnectable={false}
          deleteKeyCode={null}
          onNodesChange={(changes) => {
            const next = applyNodeChanges(changes, nodes);
            if (changes.some((c) => c.type === "position"))
              setPositions(
                Object.fromEntries(next.map((n) => [n.id, n.position])),
              );
          }}
          onNodeClick={(_, node) => {
            const region =
              node.data.branch && branchRegion(document, node.data.branch.id);
            if (region) onSelect(region);
          }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={15}
            size={1.5}
            color="#C4DCF0"
          />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </div>
      {outputMode && (
        <section className="output-result-preview" aria-label="结果示意">
          <h3>
            结果示意 <small>运行后填充，当前没有识别结果。</small>
          </h3>
          <table>
            <thead>
              <tr>
                <th>结果</th>
                <th>时刻</th>
                <th>证据</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={3}>暂无结果 · 本地草稿配置不生成检测结果</td>
              </tr>
            </tbody>
          </table>
        </section>
      )}
    </section>
  );
}
