import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ApiError, checkIntent, explain, explainLine, getRepo, getReviews, getSource, saveReview } from '../api'
import { CodePane } from '../components/CodePane'
import { ExportButton } from '../components/ExportButton'
import { FlowPane } from '../components/FlowPane'
import { IntentBox } from '../components/IntentBox'
import { ModelButton, useLlmSettings } from '../components/ModelButton'
import { loadReviewer, subscribe } from '../settings'
import { OutlinePane } from '../components/OutlinePane'
import { ExplanationReview, MismatchReview } from '../components/ReviewControls'
import { KIND_LABEL, KIND_ORDER } from '../theme'
import type { Depth, FileNode, FunctionNode, Mismatch, Review, ReviewBody, Step } from '../types'

type Loaded =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; key: string; file: FileNode; source: string }

type Explanations =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; byStep: Record<string, string> }

type LineText =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; text: string }

interface IntentState {
  busy: boolean
  error: string | null
  mismatches: Mismatch[] | null
  text: string // the description the mismatches were checked against
}

const NO_INTENT: IntentState = { busy: false, error: null, mismatches: null, text: '' }

// Texts the server uses when the model gave nothing to review.
const UNREVIEWABLE = new Set([
  'No explanation available for this step.',
  'This function is too long to explain automatically.',
])

/** Reviews are one per step and depth (explanations) or step and description (mismatches). */
function sameReview(a: Review, b: Review): boolean {
  return a.type === b.type && a.step.id === b.step.id && a.depth === b.depth && a.intent === b.intent
}

function intentNote(mismatches: Mismatch[] | null): string | null {
  if (mismatches === null) return null
  if (mismatches.length === 0) return 'No differences found. This is not a guarantee that the code is correct.'
  return mismatches.length === 1
    ? '1 step may differ from your description. Select it to see why.'
    : `${mismatches.length} steps may differ from your description. Select one to see why.`
}

/** Text with `names` from the code shown as inline code. */
function Rich(props: { text: string }) {
  const parts = props.text.split('`')
  return (
    <p>
      {parts.map((part, i) => (i % 2 === 1 && i < parts.length - 1 ? <code key={i}>{part}</code> : part))}
    </p>
  )
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : 'Something went wrong. Try again.'
}

function stepTitle(step: Step): string {
  const lines =
    step.line_start === step.line_end ? `line ${step.line_start}` : `lines ${step.line_start} to ${step.line_end}`
  return `${KIND_LABEL[step.kind]}, ${lines}`
}

/** The function a line belongs to: the innermost one, and the module only when no function contains it. */
export function owningFunction(functions: FunctionNode[], line: number): FunctionNode | null {
  let best: FunctionNode | null = null
  for (const f of functions) {
    if (line < f.line_start || line > f.line_end) continue
    const isModule = f.qualname === '<module>'
    if (!best) best = f
    else if (best.qualname === '<module>' && !isModule) best = f
    else if (!isModule && f.line_end - f.line_start < best.line_end - best.line_start) best = f
  }
  return best
}

/** The smallest step whose line range contains the line. */
export function innermostStep(fn: FunctionNode, line: number): Step | null {
  let best: Step | null = null
  for (const step of fn.steps) {
    if (line < step.line_start || line > step.line_end) continue
    if (!best || step.line_end - step.line_start < best.line_end - best.line_start) best = step
  }
  return best
}

export function FileViewPage() {
  const params = useParams()
  const id = params.id ?? ''
  const path = params['*'] ?? ''
  const [search, setSearch] = useSearchParams()
  const wantedFn = search.get('fn')

  const [loaded, setLoaded] = useState<Loaded>({ status: 'loading' })
  const [depth, setDepth] = useState<Depth>('developer')
  const [stepId, setStepId] = useState<string | null>(null)
  // Selected lines (one line or a range); null means the whole step is selected.
  const [rawSel, setRawSel] = useState<{ fn: string; start: number; end: number } | null>(null)
  const anchor = useRef<number | null>(null) // the first line of a shift-click range
  // Lines to select once their function is shown.
  const pendingLine = useRef<{ start: number; end: number } | null>(null)
  const [lineText, setLineText] = useState<LineText>({ status: 'loading' })
  const [lineAttempt, setLineAttempt] = useState(0)
  const lineCache = useRef(new Map<string, string>())
  const [explanations, setExplanations] = useState<Explanations>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [intent, setIntent] = useState<IntentState>(NO_INTENT)
  const intentRun = useRef(0)
  const [reviews, setReviews] = useState<Review[]>([])
  const [reviewError, setReviewError] = useState<string | null>(null)
  const myName = useSyncExternalStore(subscribe, loadReviewer, loadReviewer).trim()
  const by = (r: Review | undefined) => (r?.reviewer && r.reviewer !== myName ? r.reviewer : 'you')
  const llm = useLlmSettings() // a new model choice means new explanations

  useEffect(() => {
    let live = true
    setLoaded({ status: 'loading' })
    ;(async () => {
      const { model } = await getRepo(id)
      const file = model.files.find((f) => f.path === path)
      if (!file) throw new ApiError('File not found.')
      return { file, source: await getSource(id, path) }
    })().then(
      (res) => live && setLoaded({ status: 'ready', key: `${id}\n${path}`, ...res }),
      (e) => live && setLoaded({ status: 'error', message: message(e) }),
    )
    return () => {
      live = false
    }
  }, [id, path])

  // What is loaded may still be the previous file for one render after a link is followed.
  const ready = loaded.status === 'ready' && loaded.key === `${id}\n${path}` ? loaded : null
  const file = ready ? ready.file : null
  const fn = useMemo(
    () => file?.functions.find((f) => f.id === wantedFn) ?? file?.functions[0] ?? null,
    [file, wantedFn],
  )
  const fnId = fn?.id ?? null
  // A selection made in another function never applies to this one.
  const sel = rawSel && rawSel.fn === fnId ? rawSel : null
  const setSel = (next: { start: number; end: number } | null) =>
    setRawSel(next && fnId ? { fn: fnId, ...next } : null)

  useEffect(() => {
    // A line clicked in another function switches to that function and keeps the line selected.
    const n = pendingLine.current
    pendingLine.current = null
    if (fn && n !== null && n.start >= fn.line_start && n.start <= fn.line_end) {
      anchor.current = n.start
      setSel({ start: n.start, end: Math.min(n.end, fn.line_end) })
      setStepId(n.start === n.end ? (innermostStep(fn, n.start)?.id ?? null) : null)
    } else {
      setStepId(null)
      setSel(null)
    }
    setIntent(NO_INTENT)
    intentRun.current += 1 // drop any check still running for the previous function
  }, [fnId])

  useEffect(() => {
    setReviews([])
    setReviewError(null)
    if (!fnId) return
    let live = true
    getReviews(id, fnId).then(
      (found) => live && setReviews(found),
      () => {}, // reviews are an extra: the page works without them
    )
    return () => {
      live = false
    }
  }, [id, fnId])

  function review(body: Omit<ReviewBody, 'function_id'>) {
    if (!fnId) return
    setReviewError(null)
    saveReview(id, { ...body, function_id: fnId }).then(
      (saved) => setReviews((all) => [...all.filter((r) => !sameReview(r, saved)), saved]),
      (e) => setReviewError(message(e)),
    )
  }

  const flagged = useMemo(() => new Set((intent.mismatches ?? []).map((m) => m.step_id)), [intent.mismatches])

  function runIntentCheck(text: string) {
    if (!fnId) return
    const run = ++intentRun.current
    setIntent({ busy: true, error: null, mismatches: null, text })
    checkIntent(id, fnId, text).then(
      (mismatches) => run === intentRun.current && setIntent({ busy: false, error: null, mismatches, text }),
      (e) => run === intentRun.current && setIntent({ busy: false, error: message(e), mismatches: null, text }),
    )
  }

  useEffect(() => {
    if (!fnId) return
    let live = true
    setExplanations({ status: 'loading' })
    explain(id, fnId, depth).then(
      (byStep) => live && setExplanations({ status: 'ready', byStep }),
      (e) => live && setExplanations({ status: 'error', message: message(e) }),
    )
    return () => {
      live = false
    }
  }, [id, fnId, depth, attempt, llm])

  useEffect(() => {
    lineCache.current.clear() // a new model choice means new explanations
  }, [llm])

  useEffect(() => {
    if (!fnId || sel === null) return
    const { start, end } = sel
    const key = `${fnId}\0${depth}\0${start}\0${end}`
    const hit = lineCache.current.get(key)
    if (hit !== undefined) {
      setLineText({ status: 'ready', text: hit })
      return
    }
    let live = true
    setLineText({ status: 'loading' })
    ;(start === end ? explainLine(id, fnId, start, depth) : explainLine(id, fnId, start, depth, end)).then(
      (text) => {
        lineCache.current.set(key, text)
        if (live) setLineText({ status: 'ready', text })
      },
      (e) => live && setLineText({ status: 'error', message: message(e) }),
    )
    return () => {
      live = false
    }
  }, [id, fnId, sel, depth, lineAttempt, llm])

  function selectLine(n: number, extend = false) {
    if (!fn || !file) return
    const inside = n >= fn.line_start && n <= fn.line_end
    if (extend) {
      if (!inside || anchor.current === null) return
      const a = anchor.current
      setSel({ start: Math.min(a, n), end: Math.max(a, n) })
      return
    }
    const owner = owningFunction(file.functions, n)
    if (owner && owner.id !== fn.id) {
      pendingLine.current = { start: n, end: n }
      setSearch({ fn: owner.id })
      return
    }
    if (!inside) return
    anchor.current = n
    setSel({ start: n, end: n })
    setStepId(innermostStep(fn, n)?.id ?? null)
  }

  /** Several lines chosen by dragging. The range stays inside the function that owns its first line. */
  function selectRange(start: number, end: number) {
    if (!fn || !file) return
    const owner = owningFunction(file.functions, start)
    if (!owner) return
    const last = Math.min(end, owner.line_end)
    if (owner.id !== fn.id) {
      pendingLine.current = { start, end: last }
      setSearch({ fn: owner.id })
      return
    }
    anchor.current = start
    setSel({ start, end: last })
  }

  function selectWholeFunction() {
    if (!fn) return
    anchor.current = fn.line_start
    setSel({ start: fn.line_start, end: fn.line_end })
  }

  function selectStep(next: string | null) {
    setSel(null)
    setStepId(next)
  }

  if (loaded.status === 'error') {
    return (
      <main className="page-message">
        <p role="alert" className="error">
          {loaded.message}
        </p>
        <Link to={`/repo/${id}`}>Back to map</Link>
      </main>
    )
  }
  if (!ready || !file) return <main className="page-message">Loading…</main>

  const step = fn?.steps.find((s) => s.id === stepId) ?? null
  const mismatch = step ? (intent.mismatches ?? []).find((m) => m.step_id === step.id) : undefined
  const modelText = step && explanations.status === 'ready' ? explanations.byStep[step.id] : undefined
  const explanationReview = step
    ? reviews.find((r) => r.type === 'explanation' && r.step.id === step.id && r.depth === depth)
    : undefined
  const shownText =
    explanationReview?.verdict === 'corrected' ? explanationReview.final_explanation : (modelText ?? undefined)
  const mismatchReview =
    step && mismatch
      ? reviews.find((r) => r.type === 'mismatch' && r.step.id === step.id && r.intent === intent.text)
      : undefined
  const calls = fn && step ? fn.calls.filter((c) => innermostStep(fn, c.line)?.id === step.id) : []

  return (
    <main className="file-page">
      <header className="bar">
        <Link to={`/repo/${id}`}>Back to map</Link>
        <span className="file-title">{file.path}</span>
        <span className="spacer" />
        <ExportButton repoId={id} />
        <ModelButton />
        <div className="depth" role="group" aria-label="Explanation depth">
          {(['beginner', 'developer'] as const).map((d) => (
            <button key={d} type="button" aria-pressed={depth === d} onClick={() => setDepth(d)}>
              {d === 'beginner' ? 'Beginner' : 'Developer'}
            </button>
          ))}
        </div>
      </header>
      <div className="panes">
        <OutlinePane functions={file.functions} selectedId={fnId} onSelect={(next) => setSearch({ fn: next })} />
        <section className="pane flow-pane" aria-label="Flow">
          {fn ? (
            <>
              <IntentBox
                key={fn.id}
                onCheck={runIntentCheck}
                busy={intent.busy}
                error={intent.error}
                note={intentNote(intent.mismatches)}
              />
              <FlowPane fn={fn} selectedStepId={stepId} flaggedStepIds={flagged} onSelectStep={selectStep} />
              <ul className="kind-key" aria-label="Step colours">
                {KIND_ORDER.filter((kind) => fn.steps.some((s) => s.kind === kind)).map((kind) => (
                  <li key={kind} className={`kind-${kind}`}>
                    {KIND_LABEL[kind]}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="empty">
              {file.parse_error
                ? `Could not parse this file: ${file.parse_error}`
                : 'This file has no functions or top-level code to show.'}
            </p>
          )}
        </section>
        <section className="pane code-pane" aria-label="Code">
          {fn && (
            <div className="explanation">
              <h2>Explanation</h2>
              <div className="line-tools">
                <button type="button" className="secondary" onClick={selectWholeFunction}>
                  Explain whole function
                </button>
                <span className="fine">Click a line to explain it. Drag across lines, or shift-click, to explain a range.</span>
              </div>
              {fn && sel !== null && (
                <div className="line-explanation">
                  <p className="line-title">
                    {sel.start === sel.end
                      ? `Line ${sel.start}`
                      : sel.start === fn.line_start && sel.end === fn.line_end
                        ? `Whole function, lines ${sel.start} to ${sel.end}`
                        : `Lines ${sel.start} to ${sel.end}`}
                  </p>
                  {lineText.status === 'loading' && <p>Explaining…</p>}
                  {lineText.status === 'ready' && <Rich text={lineText.text} />}
                  {lineText.status === 'error' && (
                    <>
                      <p role="alert" className="error">
                        {lineText.message}
                      </p>
                      <button type="button" className="secondary" onClick={() => setLineAttempt((n) => n + 1)}>
                        Retry
                      </button>
                    </>
                  )}
                  <div className="line-nav">
                    <button
                      type="button"
                      className="secondary"
                      disabled={sel.start <= fn.line_start}
                      onClick={() => selectLine(sel.start - 1)}
                    >
                      Previous line
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      disabled={sel.end >= fn.line_end}
                      onClick={() => selectLine(sel.end + 1)}
                    >
                      Next line
                    </button>
                  </div>
                  {step && sel.start === sel.end && explanations.status === 'ready' && <p className="fine">Part of this step:</p>}
                </div>
              )}
              {step && (sel === null || (sel !== null && sel.start === sel.end && explanations.status === 'ready')) && (
                <p className={`step-title kind-${step.kind}`}>{stepTitle(step)}</p>
              )}
              {mismatch && <p className="mismatch">{`Possible mismatch: ${mismatch.reason}`}</p>}
              {step && mismatch && (
                <MismatchReview
                  review={mismatchReview}
                  by={by(mismatchReview)}
                  onVerdict={(verdict) =>
                    review({ type: 'mismatch', step_id: step.id, intent: intent.text, reason: mismatch.reason, verdict })
                  }
                />
              )}
              {sel === null && explanations.status === 'loading' && <p>Explaining…</p>}
              {sel === null && explanations.status === 'error' && (
                <>
                  <p role="alert" className="error">
                    {explanations.message}
                  </p>
                  <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
                    Retry
                  </button>
                </>
              )}
              {explanations.status === 'ready' && !step && sel === null && <p>Select a step in the flow or a line of code.</p>}
              {explanations.status === 'ready' && step && (sel === null || sel !== null && sel.start === sel.end) && (
                <Rich text={shownText ?? 'No explanation available for this step.'} />
              )}
              {sel === null && step && modelText && shownText && !UNREVIEWABLE.has(modelText) && (
                <ExplanationReview
                  key={`${step.id}:${depth}`}
                  shown={shownText}
                  review={explanationReview}
                  by={by(explanationReview)}
                  onAccept={() =>
                    review({ type: 'explanation', step_id: step.id, depth, explanation: modelText, verdict: 'accepted' })
                  }
                  onCorrect={(corrected) =>
                    review({
                      type: 'explanation',
                      step_id: step.id,
                      depth,
                      explanation: modelText,
                      verdict: 'corrected',
                      corrected,
                    })
                  }
                />
              )}
              {reviewError && (
                <p role="alert" className="error">
                  {reviewError}
                </p>
              )}
              {calls.length > 0 && (sel === null || (sel.start === sel.end && explanations.status === 'ready')) && (
                <ul className="calls" aria-label="Calls in this step">
                  {calls.map((c, i) => {
                    const target = c.target
                    return (
                      <li key={`${c.name}-${c.line}-${i}`}>
                        {target ? (
                          <Link to={`/repo/${id}/file/${target.split('::')[0]}?fn=${encodeURIComponent(target)}`}>
                            {c.name}
                          </Link>
                        ) : (
                          <span className="unresolved">{`${c.name} (unresolved)`}</span>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          )}
          <CodePane
            source={ready.source}
            highlight={
              sel !== null
                ? { start: sel.start, end: sel.end, kind: sel.start === sel.end ? step?.kind : undefined }
                : step
                  ? { start: step.line_start, end: step.line_end, kind: step.kind }
                  : null
            }
            focusLine={fn ? fn.line_start : null}
            onLineClick={selectLine}
            onRangeSelect={selectRange}
          />
        </section>
      </div>
    </main>
  )
}
