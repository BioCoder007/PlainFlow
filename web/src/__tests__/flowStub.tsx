/* A stand-in for @xyflow/react in component tests: jsdom has no layout, so the
   real canvas cannot render. It draws each node with the page's own node
   component and forwards clicks, and lists edges as text. */
import type { ComponentType, ReactNode } from 'react'

type StubNode = { id: string; type?: string; data: { label?: ReactNode } & Record<string, unknown> }
type StubEdge = {
  id: string
  source: string
  target: string
  label?: ReactNode
  style?: { strokeDasharray?: string }
  data?: { tone?: string }
}

export function ReactFlow(props: {
  nodes: StubNode[]
  edges: StubEdge[]
  nodeTypes?: Record<string, ComponentType<{ id: string; data: StubNode['data'] }>>
  onNodeClick?: (event: unknown, node: StubNode) => void
  children?: ReactNode
}) {
  return (
    <div data-testid="flow">
      {props.nodes.map((node) => {
        const Custom = node.type ? props.nodeTypes?.[node.type] : undefined
        return (
          <div key={node.id} data-testid={`node-${node.id}`} onClick={() => props.onNodeClick?.({}, node)}>
            {Custom ? <Custom id={node.id} data={node.data} /> : node.data.label}
          </div>
        )
      })}
      {props.edges.map((edge) => (
        <div
          key={edge.id}
          data-testid={`edge-${edge.source}-${edge.target}`}
          data-dashed={edge.style?.strokeDasharray ? 'yes' : 'no'}
          data-tone={edge.data?.tone}
        >
          {edge.label}
        </div>
      ))}
      {props.children}
    </div>
  )
}

export const Background = () => null
export const Controls = () => null
export const MiniMap = () => null
export const Handle = () => null
export const Position = { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' }
export const MarkerType = { ArrowClosed: 'arrowclosed' }
