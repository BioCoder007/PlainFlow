import {
  Background,
  Controls,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { useMemo } from "react";
import { layoutGraph } from "../layout";
import { EDGE_COLOR, edgeTone, INK } from "../theme";
import type { FunctionNode, Step, StepKind } from "../types";
import { useMovable } from "../useMovable";

interface StepData extends Record<string, unknown> {
  label: string;
  kind: StepKind;
  selected: boolean;
  flagged: boolean;
}

function StepNodeView({ data }: { data: StepData }) {
  const classes = ["step-node", `kind-${data.kind}`];
  if (data.selected) classes.push("selected");
  if (data.flagged) classes.push("flagged");
  return (
    <div className={classes.join(" ")} title={data.label}>
      <Handle type="target" position={Position.Top} />
      <span className="step-label">{data.label}</span>
      {data.flagged && (
        <span className="flag-badge" aria-label="Possible mismatch">
          !
        </span>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = { step: StepNodeView };

function size(step: Step): { width: number; height: number } {
  const text = Math.min(280, Math.max(110, step.label.length * 7.4 + 30));
  return step.kind === "branch"
    ? { width: text * 1.5 + 30, height: 68 }
    : { width: text, height: 40 };
}

export function FlowPane(props: {
  fn: FunctionNode;
  selectedStepId: string | null;
  flaggedStepIds: Set<string>;
  onSelectStep: (id: string) => void;
}) {
  const { fn, selectedStepId, flaggedStepIds } = props;

  const positions = useMemo(
    () =>
      layoutGraph(
        fn.steps.map((s) => ({ id: s.id, ...size(s) })),
        fn.edges,
        "TB",
      ),
    [fn],
  );

  const base: Node[] = useMemo(
    () =>
      fn.steps.map((step) => ({
        id: step.id,
        type: "step",
        position: positions[step.id],
        ...size(step),
        data: {
          label: step.label,
          kind: step.kind,
          selected: step.id === selectedStepId,
          flagged: flaggedStepIds.has(step.id),
        } satisfies StepData,
      })),
    [fn, positions, selectedStepId, flaggedStepIds],
  );
  const { nodes, onNodesChange, reset, hasMoved } = useMovable(fn.id, base);

  const edges: Edge[] = fn.edges.map((edge) => {
    const tone = edgeTone(edge.label);
    const color = EDGE_COLOR[tone];
    return {
      id: `${edge.source}->${edge.target}:${edge.label ?? ""}`,
      source: edge.source,
      target: edge.target,
      label: edge.label ?? undefined,
      type: "smoothstep",
      animated: tone === "loop", // the path that repeats is the one that moves
      data: { tone },
      className: `tone-${tone}`, // label colours are set in index.css
      style: {
        stroke: color,
        strokeWidth: 1.6,
        strokeDasharray: tone === "except" ? "5 4" : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color },
    };
  });

  return (
    <div className="flow-canvas">
      <ReactFlow
        key={fn.id}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => props.onSelectStep(node.id)}
        nodesConnectable={false}
        onNodesChange={onNodesChange}
        nodesDraggable
        elementsSelectable
        colorMode="dark"
        fitView
        fitViewOptions={{ maxZoom: 1 }}
        minZoom={0.1}
      >
        <Background color={INK.line} gap={22} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {hasMoved && (
        <button
          type="button"
          className="secondary reset-layout"
          onClick={reset}
        >
          Reset layout
        </button>
      )}
    </div>
  );
}
