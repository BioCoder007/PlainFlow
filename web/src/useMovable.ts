import { applyNodeChanges, type Node, type NodeChange } from '@xyflow/react'
import { useCallback, useMemo, useState } from 'react'

interface Held {
  key: string
  nodes: Record<string, Node> // nodes as the diagram last reported them (measured size included)
  moved: Record<string, true> // ids the user has dragged
}

function merge(base: Node[], held: Held | null): Node[] {
  return base.map((b) => {
    const kept = held?.nodes[b.id]
    if (!kept) return b
    return { ...kept, ...b, position: held.moved[b.id] ? kept.position : b.position }
  })
}

/**
 * Lets the user drag diagram nodes. `base` is the laid-out diagram; the hook returns the same
 * nodes with any dragged positions kept, for one diagram (`key`). A different diagram starts
 * from its own layout again.
 */
export function useMovable(key: string, base: Node[]) {
  const [held, setHeld] = useState<Held>({ key, nodes: {}, moved: {} })
  const current = held.key === key ? held : null
  const nodes = useMemo(() => merge(base, current), [base, current])

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setHeld((h) => {
        const mine = h.key === key ? h : { key, nodes: {}, moved: {} }
        const next = applyNodeChanges(changes, merge(base, mine))
        const moved = { ...mine.moved }
        for (const c of changes) if (c.type === 'position' && c.position) moved[c.id] = true
        return { key, nodes: Object.fromEntries(next.map((n) => [n.id, n])), moved }
      })
    },
    [key, base],
  )
  const reset = useCallback(() => setHeld((h) => ({ key, nodes: h.key === key ? h.nodes : {}, moved: {} })), [key])
  return { nodes, onNodesChange, reset, hasMoved: current !== null && Object.keys(current.moved).length > 0 }
}
