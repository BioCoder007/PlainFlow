import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

const KEYWORDS = new Set(
  (
    'False None True and as assert async await break case class continue def del elif else except finally for from ' +
    'global if import in is lambda match nonlocal not or pass raise return try while with yield'
  ).split(' '),
)
const TOKEN = /(#.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b\d[\d_.]*\b)|([A-Za-z_]\w*)/g
const TRIPLE = /"""|'''/

type Piece = { text: string; cls: string | null }

/** Colour one stretch of code that is outside any triple-quoted string. */
function plain(text: string): Piece[] {
  const out: Piece[] = []
  let last = 0
  for (const m of text.matchAll(TOKEN)) {
    const cls = m[1] ? 'tok-com' : m[2] ? 'tok-str' : m[3] ? 'tok-num' : KEYWORDS.has(m[4]) ? 'tok-kw' : null
    if (!cls) continue
    if (m.index > last) out.push({ text: text.slice(last, m.index), cls: null })
    out.push({ text: m[0], cls })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last), cls: null })
  return out
}

/**
 * Light colouring, line by line, tracking triple-quoted strings across lines.
 * It only wraps text in spans; the text itself is never changed.
 */
function colourLines(lines: string[]): Piece[][] {
  let open: string | null = null // the triple quote we are inside, if any
  return lines.map((line) => {
    const pieces: Piece[] = []
    let rest = line
    while (rest.length > 0) {
      if (open) {
        const end = rest.indexOf(open)
        if (end === -1) {
          pieces.push({ text: rest, cls: 'tok-str' })
          rest = ''
        } else {
          pieces.push({ text: rest.slice(0, end + 3), cls: 'tok-str' })
          rest = rest.slice(end + 3)
          open = null
        }
        continue
      }
      const start = rest.search(TRIPLE)
      const hash = rest.indexOf('#')
      if (start === -1 || (hash !== -1 && hash < start)) {
        pieces.push(...plain(rest))
        rest = ''
        continue
      }
      pieces.push(...plain(rest.slice(0, start)))
      open = rest.slice(start, start + 3)
      const end = rest.indexOf(open, start + 3)
      if (end === -1) {
        pieces.push({ text: rest.slice(start), cls: 'tok-str' })
        rest = ''
      } else {
        pieces.push({ text: rest.slice(start, end + 3), cls: 'tok-str' })
        rest = rest.slice(end + 3)
        open = null
      }
    }
    return pieces
  })
}

function render(pieces: Piece[]): ReactNode[] {
  return pieces.map((p, i) =>
    p.cls ? (
      <span key={i} className={p.cls}>
        {p.text}
      </span>
    ) : (
      p.text
    ),
  )
}

export function CodePane(props: {
  source: string
  highlight: { start: number; end: number; kind?: string } | null
  /** Line to bring into view when nothing is highlighted, e.g. the function's first line. */
  focusLine: number | null
  /** extend is true for a shift-click, which selects a range. */
  onLineClick: (line: number, extend: boolean) => void
  /** Called when the user drags across several lines. */
  onRangeSelect?: (start: number, end: number) => void
}) {
  const { source, highlight, focusLine } = props
  const container = useRef<HTMLPreElement | null>(null)
  const lines = useMemo(() => source.split('\n'), [source])
  const coloured = useMemo(() => colourLines(lines), [lines])
  const target = highlight ? highlight.start : focusLine
  // A drag in progress: the line it started on and the line the pointer is over.
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null)
  const dragRef = useRef<{ from: number; to: number; y: number } | null>(null)
  const onRangeSelect = props.onRangeSelect

  useEffect(() => {
    if (!drag) return
    const lineAt = (x: number, y: number) => {
      const el = document.elementFromPoint?.(x, y)?.closest?.('[data-line]')
      return el ? Number(el.getAttribute('data-line')) : null
    }
    const move = (e: MouseEvent) => {
      const d = dragRef.current
      if (!d) return
      d.y = e.clientY
      const n = lineAt(e.clientX, e.clientY)
      if (n && n !== d.to) {
        d.to = n
        setDrag({ from: d.from, to: n })
      }
    }
    const up = () => {
      const d = dragRef.current
      dragRef.current = null
      setDrag(null)
      if (d && d.to !== d.from) onRangeSelect?.(Math.min(d.from, d.to), Math.max(d.from, d.to))
    }
    // Scroll the code when the pointer is held near the top or bottom edge.
    const timer = setInterval(() => {
      const box = container.current
      const d = dragRef.current
      if (!box || !d) return
      const r = box.getBoundingClientRect()
      const step = d.y < r.top + 28 ? -18 : d.y > r.bottom - 28 ? 18 : 0
      if (step === 0) return
      box.scrollTop += step
      const n = lineAt(r.left + 60, Math.min(Math.max(d.y, r.top + 4), r.bottom - 4))
      if (n && n !== d.to) {
        d.to = n
        setDrag({ from: d.from, to: n })
      }
    }, 40)
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      clearInterval(timer)
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag !== null])
  const dragging = drag && drag.from !== drag.to ? { start: Math.min(drag.from, drag.to), end: Math.max(drag.from, drag.to) } : null

  useEffect(() => {
    if (target === null) return
    const el = container.current?.querySelector(`[data-line="${target}"]`)
    // A newly opened function goes to the top of the pane; a step only scrolls if it is off-screen.
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: highlight ? 'nearest' : 'start' })
  }, [target, source])

  return (
    <pre className={dragging ? 'code selecting' : 'code'} ref={container}>
      {lines.map((_, i) => {
        const n = i + 1
        const shown = dragging ?? highlight
        const on = shown !== null && n >= shown.start && n <= shown.end
        return (
          <div
            key={n}
            data-line={n}
            data-testid={`line-${n}`}
            className={on ? `code-line highlighted${!dragging && highlight?.kind ? ` kind-${highlight.kind}` : ''}` : 'code-line'}
            onMouseDown={(e) => {
              if (e.button !== 0) return
              e.preventDefault() // lines are selected, not text
              if (e.shiftKey) return
              dragRef.current = { from: n, to: n, y: e.clientY }
              setDrag({ from: n, to: n })
            }}
            onMouseEnter={() => {
              const d = dragRef.current
              if (d && d.to !== n) {
                d.to = n
                setDrag({ from: d.from, to: n })
              }
            }}
            onClick={(e) => props.onLineClick(n, e.shiftKey)}
          >
            <span className="ln">{n}</span>
            <span className="src">{render(coloured[i])}</span>
          </div>
        )
      })}
    </pre>
  )
}
