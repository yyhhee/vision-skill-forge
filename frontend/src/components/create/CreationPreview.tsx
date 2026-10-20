import { useEffect, useRef, useState } from "react";
import {
  ReactFlow,
  Handle,
  Position,
  MarkerType,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  BellIcon,
  InfinityIcon,
  PantsIcon,
  ShareNetworkIcon,
  TShirtIcon,
  UsersIcon,
} from "@phosphor-icons/react";
import {
  branchRegion,
  colorHex,
  colorNames,
  type SkillDocument,
} from "../../data/document";

type PreviewNode = Node<
  { doc: SkillDocument; branchId?: string; kind: string },
  "preview"
>;
function PreviewCard({ data }: NodeProps<PreviewNode>) {
  const { doc, kind } = data;
  const branch = doc.branches.find((b) => b.id === data.branchId);
  if (branch) {
    const region = doc.regions.find(
      (r) => r.id === branchRegion(doc, branch.id),
    );
    const attributes = doc.conditions.filter(
      (c) => branch.logic.members.includes(c.id) && c.kind === "visible_color",
    );
    const count = doc.conditions.find(
      (c) => branch.logic.members.includes(c.id) && c.kind === "count",
    );
    return (
      <section
        className={`creation-branch ${region?.colorIdentity}`}
        aria-label={`${branch.name}理解预览`}
      >
        <header>
          <ShareNetworkIcon size={34} weight="bold" />
          <strong>
            {region?.name}：
            {count
              ? `人数至少${count.value}人`
              : `存在穿${colorNames[attributes[0]?.color ?? ""]}上衣、${colorNames[attributes[1]?.color ?? ""]}裤子的人员`}
          </strong>
        </header>
        <div className="creation-evidence">
          <div>
            {attributes.map((c) => {
              const Icon = c.part === "lower" ? PantsIcon : TShirtIcon;
              return (
                <div key={c.id}>
                  <Icon
                    size={30}
                    weight="fill"
                    style={{ color: colorHex[c.color ?? "gray"] }}
                  />
                  <span>穿{c.label}</span>
                </div>
              );
            })}
            {count && (
              <div>
                <UsersIcon size={31} weight="fill" />
                <span>
                  区域内的
                  <br />
                  人员数量
                </span>
              </div>
            )}
          </div>
          {!count && <span className="logic-bracket" aria-hidden="true" />}
          <span className="creation-evidence-result">
            {count ? (
              `人数 ≥ ${count.value}`
            ) : (
              <>
                {region?.name}内<br />
                同时满足
              </>
            )}
          </span>
        </div>
        <Handle
          type="source"
          position={Position.Bottom}
          isConnectable={false}
        />
      </section>
    );
  }
  const Icon = kind === "final" ? InfinityIcon : BellIcon;
  return (
    <div className={`creation-result ${kind}`}>
      {kind === "final" ? (
        doc.branches.map((branch, index) => (
          <Handle
            key={branch.id}
            id={branch.id}
            type="target"
            position={Position.Top}
            isConnectable={false}
            style={{ left: index === 0 ? "41.5%" : "58%" }}
          />
        ))
      ) : (
        <Handle type="target" position={Position.Top} isConnectable={false} />
      )}
      <Icon size={43} weight={kind === "final" ? "bold" : "fill"} />
      <div>
        <strong>
          {kind === "final"
            ? `最终关系：${doc.final.label}`
            : `输出：${doc.outputs[0].name}`}
        </strong>
        <small>
          {kind === "final"
            ? doc.final.operator
            : "当上述条件同时满足时，触发区域告警事件。"}
        </small>
      </div>
      {kind === "final" && (
        <Handle
          type="source"
          position={Position.Bottom}
          isConnectable={false}
        />
      )}
    </div>
  );
}
const nodeTypes = { preview: PreviewCard };
export function CreationPreview({
  document: doc,
}: {
  document: SkillDocument;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(574);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.observe(root.current!);
    return () => observer.disconnect();
  }, []);
  const nodes: PreviewNode[] = [
    ...doc.branches.map((branch, index) => ({
      id: branch.id,
      type: "preview" as const,
      position: { x: index === 0 ? 0 : 305, y: 0 },
      style: { width: index === 0 ? 294 : 269 },
      data: { doc, branchId: branch.id, kind: "branch" },
    })),
    {
      id: doc.final.id,
      type: "preview",
      position: { x: 115, y: 357 },
      style: { width: 350 },
      data: { doc, kind: "final" },
    },
    {
      id: doc.outputs[0].id,
      type: "preview",
      position: { x: 99, y: 464 },
      style: { width: 382 },
      data: { doc, kind: "output" },
    },
  ];
  const edges = [
    ...doc.branches.map((b, index) => ({
      id: `edge-${b.id}`,
      source: b.id,
      target: doc.final.id,
      targetHandle: b.id,
      style: { stroke: index ? "#00aab5" : "#ff7900", strokeWidth: 2 },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: index ? "#00aab5" : "#ff7900",
      },
      type: "smoothstep",
    })),
    {
      id: "edge-output",
      source: doc.final.id,
      target: doc.outputs[0].id,
      type: "smoothstep",
      style: { stroke: "#4f46e5", strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#4f46e5" },
    },
  ];
  return (
    <div
      ref={root}
      className="creation-diagram"
      style={{ height: 548 * Math.min(width / 574, 1) }}
      data-testid="creation-preview"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        viewport={{
          x: Math.max((width - 574) / 2, 0),
          y: 0,
          zoom: Math.min(width / 574, 1),
        }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        minZoom={0.2}
        maxZoom={1}
      />
    </div>
  );
}
