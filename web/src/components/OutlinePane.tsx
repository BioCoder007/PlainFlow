import type { FunctionNode } from '../types'

export function OutlinePane(props: {
  functions: FunctionNode[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <nav className="pane outline" aria-label="Functions">
      <h2>Functions</h2>
      {props.functions.map((fn) => (
        <button
          key={fn.id}
          type="button"
          aria-current={fn.id === props.selectedId ? 'true' : 'false'}
          title={fn.qualname}
          onClick={() => props.onSelect(fn.id)}
        >
          {fn.qualname}
        </button>
      ))}
    </nav>
  )
}
