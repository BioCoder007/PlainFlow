import { expect, it } from 'vitest'
import { layoutGraph } from '../layout'

const nodes = [
  { id: 'a', width: 100, height: 40 },
  { id: 'b', width: 100, height: 40 },
]
const edges = [{ source: 'a', target: 'b' }]

it('places a target to the right of its source in LR layout', () => {
  const pos = layoutGraph(nodes, edges, 'LR')
  expect(pos.b.x).toBeGreaterThan(pos.a.x + 100)
})

it('places a target below its source in TB layout', () => {
  const pos = layoutGraph(nodes, edges, 'TB')
  expect(pos.b.y).toBeGreaterThan(pos.a.y + 40)
})

it('gives every node a position, including unconnected ones, and ignores edges to unknown nodes', () => {
  const pos = layoutGraph([...nodes, { id: 'c', width: 100, height: 40 }], [{ source: 'a', target: 'zzz' }], 'LR')
  expect(Object.keys(pos).sort()).toEqual(['a', 'b', 'c'])
})
