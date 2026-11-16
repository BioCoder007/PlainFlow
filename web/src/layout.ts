import dagre from '@dagrejs/dagre'

export interface LayoutNode {
  id: string
  width: number
  height: number
}

/** Top-left positions for each node, laid out left-to-right or top-to-bottom. */
export function layoutGraph(
  nodes: LayoutNode[],
  edges: { source: string; target: string }[],
  direction: 'LR' | 'TB',
): Record<string, { x: number; y: number }> {
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({ rankdir: direction, nodesep: 36, ranksep: 64, marginx: 16, marginy: 16 })
  graph.setDefaultEdgeLabel(() => ({}))
  const ids = new Set(nodes.map((n) => n.id))
  for (const n of nodes) graph.setNode(n.id, { width: n.width, height: n.height })
  for (const e of edges) {
    if (ids.has(e.source) && ids.has(e.target) && e.source !== e.target) graph.setEdge(e.source, e.target)
  }
  dagre.layout(graph)
  const positions: Record<string, { x: number; y: number }> = {}
  for (const n of nodes) {
    const placed = graph.node(n.id)
    positions[n.id] = { x: placed.x - n.width / 2, y: placed.y - n.height / 2 }
  }
  return positions
}
