import { useMemo, useState } from "react";
import "@xyflow/react/dist/style.css";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  type Node,
  type Edge,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  ArrowsOutIcon,
  BellIcon,
  ClockIcon,
  InfinityIcon,
  PencilSimpleIcon,
  PlusIcon,
  ShareNetworkIcon,
  UsersIcon,
} from "@phosphor-icons/react";
import { Button, IconButton } from "./ui";
import { conditionLabel, type SkillDocument } from "../data/document";
export function OrchestrationCanvas({
  document: doc,
  onEdit,
  onAdd,
}: {
  document: SkillDocument;
  onEdit: (id: string, kind?: string) => void;
  onAdd: () => void;
}) {
  const [instance, setInstance] = useState<ReactFlowInstance | null>(null);
  const primary =
    doc.groups.find((g) => g.operator === "SEQUENCE") ?? doc.groups[0];
  const graph = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    const makeEdge = (
      source: string,
      target: string,
      sequence = false,
      label?: string,
    ) =>
      edges.push({
        id: `${source}-${target}`,
        source,
        target,
        type: sequence ? "straight" : "smoothstep",
        style: {
          stroke: sequence ? "#4F46E5" : "#14B8A6",
          strokeWidth: 2,
          strokeDasharray: sequence ? "6 4" : undefined,
        },
        label,
        labelStyle: { fontSize: 12, fill: "#4338CA" },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: sequence ? "#4F46E5" : "#14B8A6",
        },
      });
    const joinGroup = doc.groups.find(
      (g) => g.id !== primary?.id && g.members.includes(primary?.id ?? ""),
    );
    // Expanded two-stage view is a presentation of the exact graph, never a substitute graph.
    // Arbitrary nesting/reuse is shown as compact group nodes so shared references aren't duplicated.
    if (
      !primary ||
      doc.groups.length > 2 ||
      primary.members.some((id) => doc.groups.some((g) => g.id === id)) ||
      doc.final.members.length !== 1 ||
      doc.final.members[0] !== joinGroup?.id
    ) {
      const label = (id: string) =>
        doc.branches.find((b) => b.id === id)?.name ??
        doc.groups.find((g) => g.id === id)?.name ??
        id;
      doc.branches.forEach((b, index) =>
        nodes.push({
          id: b.id,
          position: { x: 30 + index * 280, y: 30 },
          style: { width: 245, border: "2px solid #14B8A6" },
          data: {
            label: (
              <button
                className="graph-summary"
                onClick={() => onEdit(b.id, "branch")}
              >
                <ShareNetworkIcon size={28} />
                <strong>
                  {b.name}
                  <small>
                    {b.logic.operator} · {b.logic.members.length}项条件
                  </small>
                </strong>
              </button>
            ),
          },
        }),
      );
      const levels = new Map<string, number>();
      const depth = (id: string, seen = new Set<string>()): number => {
        if (seen.has(id)) return 1;
        const g = doc.groups.find((n) => n.id === id);
        if (!g) return 0;
        return (
          1 +
          Math.max(0, ...g.members.map((m) => depth(m, new Set([...seen, id]))))
        );
      };
      doc.groups.forEach((g) => {
        const level = depth(g.id);
        const col = levels.get(String(level)) ?? 0;
        levels.set(String(level), col + 1);
        nodes.push({
          id: g.id,
          position: { x: 60 + col * 290, y: 30 + level * 150 },
          style: { width: 260, border: "1.5px solid #4F46E5" },
          data: {
            label: (
              <button
                className="graph-summary"
                onClick={() => onEdit(g.id, "group")}
              >
                <ShareNetworkIcon size={28} />
                <strong>
                  {g.name}
                  <small>{g.operator} · 可复用组</small>
                </strong>
              </button>
            ),
          },
        });
        g.members.forEach((m) => makeEdge(m, g.id, false, g.operator));
        if (g.operator === "SEQUENCE")
          g.members
            .slice(1)
            .forEach((m, i) =>
              makeEdge(
                g.members[i],
                m,
                true,
                `${label(g.members[i])} → ${label(m)} · ${g.transition?.minGapSeconds}–${g.transition?.maxGapSeconds}秒`,
              ),
            );
      });
      const finalY =
        210 + Math.max(0, ...doc.groups.map((g) => depth(g.id))) * 150;
      nodes.push({
        id: doc.final.id,
        position: { x: 310, y: finalY },
        style: { width: 240, border: "1.5px solid #4F46E5" },
        data: {
          label: (
            <button
              className="graph-summary"
              onClick={() => onEdit(doc.final.id, "final")}
            >
              <InfinityIcon size={32} />
              <strong>
                最终判定<small>{doc.final.operator}</small>
              </strong>
            </button>
          ),
        },
      });
      doc.final.members.forEach((m) => makeEdge(m, doc.final.id));
      doc.outputs.forEach((o, i) => {
        nodes.push({
          id: o.id,
          position: { x: 300 + i * 270, y: finalY + 140 },
          style: { width: 250, border: "1.5px solid #4F46E5" },
          data: {
            label: (
              <button
                className="graph-summary"
                onClick={() => onEdit(o.id, "output")}
              >
                <BellIcon size={32} />
                <strong>{o.name}</strong>
              </button>
            ),
          },
        });
        if (o.source) makeEdge(o.source, o.id);
      });
      return { nodes, edges };
    }
    if (primary) {
      nodes.push({
        id: primary.id,
        position: { x: 105, y: 30 },
        style: {
          width: Math.max(665, primary.members.length * 390 - 115),
          height: 260,
          border: "1.5px solid #4F46E5",
          background: "#F5F5FF",
          padding: 0,
        },
        data: {
          label: (
            <button
              className="group-heading"
              onClick={() => onEdit(primary.id, "group")}
            >
              <ShareNetworkIcon size={24} />组 G：{primary.name}
              <PencilSimpleIcon size={20} />
            </button>
          ),
        },
      });
      primary.members.forEach((id, index) => {
        const branch = doc.branches.find((b) => b.id === id);
        const nested = doc.groups.find((g) => g.id === id);
        nodes.push({
          id,
          position: { x: 18 + index * 390, y: 66 },
          parentId: primary.id,
          extent: "parent",
          sourcePosition: "right" as never,
          targetPosition: "left" as never,
          style: {
            width: 235,
            height: 174,
            border: `2px solid ${index === 0 ? "#F59E0B" : "#14B8A6"}`,
            background: "white",
            padding: 14,
          },
          data: {
            label: (
              <div className="orchestration-node">
                <button onClick={() => onEdit(id, branch ? "branch" : "group")}>
                  <ShareNetworkIcon size={28} />
                  <strong>{branch?.name ?? nested?.name ?? "无效成员"}</strong>
                  <PencilSimpleIcon size={18} />
                </button>
                <small>{branch ? "独立分支条件" : "引用可复用编排组"}</small>
                {branch?.logic.members.slice(0, 2).map((cid) => (
                  <button
                    key={cid}
                    className="condition-row"
                    onClick={() => onEdit(cid)}
                  >
                    <UsersIcon size={22} />
                    {conditionLabel(doc.conditions.find((c) => c.id === cid)!)}
                  </button>
                ))}
                {branch?.time.mode !== "immediate" && branch && (
                  <small>
                    <ClockIcon size={16} />
                    持续 {branch.time.durationSeconds} 秒
                  </small>
                )}
              </div>
            ),
          },
        });
        if (index > 0 && primary.operator === "SEQUENCE")
          makeEdge(
            primary.members[index - 1],
            id,
            primary.operator === "SEQUENCE",
            primary.operator === "SEQUENCE"
              ? `${primary.transition?.from === "previous.end" ? "结束" : primary.transition?.from === "previous.start" ? "开始" : "成立"}→开始·${primary.transition?.minGapSeconds}–${primary.transition?.maxGapSeconds}秒`
              : primary.operator,
          );
      });
    }
    const remaining = doc.branches.filter(
      (b) => !primary?.members.includes(b.id),
    );
    remaining.forEach((branch, index) => {
      nodes.push({
        id: branch.id,
        position: { x: 28 + index * 280, y: 340 },
        style: {
          width: 260,
          minHeight: 165,
          border: "2px solid #14B8A6",
          padding: 16,
        },
        data: {
          label: (
            <div className="orchestration-node">
              <button onClick={() => onEdit(branch.id, "branch")}>
                <ShareNetworkIcon size={28} />
                <strong>{branch.name}</strong>
                <PencilSimpleIcon size={18} />
              </button>
              {branch.logic.members.map((id) => (
                <button
                  className="condition-row"
                  key={id}
                  onClick={() => onEdit(id)}
                >
                  <UsersIcon size={24} />
                  {conditionLabel(doc.conditions.find((c) => c.id === id)!)}
                </button>
              ))}
            </div>
          ),
        },
      });
    });
    nodes.push({
      id: "join",
      position: { x: 440, y: 374 },
      style: { width: 235, height: 64, border: "1.5px solid #4F46E5" },
      data: {
        label: (
          <button
            className="graph-summary"
            onClick={() =>
              onEdit(
                joinGroup?.id ?? doc.final.id,
                joinGroup ? "group" : "final",
              )
            }
          >
            <InfinityIcon size={36} />
            <strong>
              {joinGroup?.operator === "OR" ? "任一有效" : "全部同时有效"}
              <small>{joinGroup?.operator ?? doc.final.operator}</small>
            </strong>
          </button>
        ),
      },
    });
    joinGroup?.members.forEach((id) => makeEdge(id, "join"));
    nodes.push({
      id: doc.outputs[0].id,
      position: { x: 430, y: 515 },
      style: { width: 250, height: 75, border: "1.5px solid #4F46E5" },
      data: {
        label: (
          <button
            className="graph-summary"
            onClick={() => onEdit(doc.outputs[0].id, "output")}
          >
            <BellIcon size={38} weight="fill" />
            <strong>
              {doc.outputs[0].name}
              <small>触发已配置的业务结果</small>
            </strong>
          </button>
        ),
      },
    });
    makeEdge(
      doc.outputs[0].source === doc.final.id ? "join" : doc.outputs[0].source,
      doc.outputs[0].id,
    );
    return { nodes, edges };
  }, [doc, primary, onEdit]);
  return (
    <section className="panel orchestration-panel" aria-label="编排画布">
      <header className="panel-header">
        <h2>编排画布</h2>
        <small>实线：普通依赖　虚线：显式顺序关系</small>
        <Button icon={PlusIcon} onClick={onAdd}>
          新增组
        </Button>
        <IconButton
          icon={ArrowsOutIcon}
          label="适配编排画布"
          onClick={() => instance?.fitView({ padding: 0.1 })}
        />
      </header>
      <div className="orchestration-flow">
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          onInit={setInstance}
          nodesConnectable={false}
          deleteKeyCode={null}
          defaultViewport={{ x: 10, y: 0, zoom: 1 }}
          minZoom={0.25}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={15}
            color="#C4DCF0"
          />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <nav className="group-tabs" aria-label="已保存编排组">
        {doc.groups.map((g) => (
          <Button key={g.id} onClick={() => onEdit(g.id, "group")}>
            {g.name}
          </Button>
        ))}
      </nav>
    </section>
  );
}
