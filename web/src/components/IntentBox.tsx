import { useState } from 'react'

export const MAX_INTENT_CHARS = 1000

export function IntentBox(props: {
  onCheck: (intent: string) => void
  busy: boolean
  error: string | null
  note: string | null
}) {
  const [text, setText] = useState('')
  const trimmed = text.trim()
  const over = trimmed.length > MAX_INTENT_CHARS
  return (
    <div className="intent">
      <label htmlFor="intent-text">What should this do?</label>
      <textarea
        id="intent-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Describe what this function is meant to do, in your own words."
      />
      <div className="intent-row">
        <button
          type="button"
          className="secondary"
          disabled={props.busy || trimmed.length === 0 || over}
          onClick={() => props.onCheck(trimmed)}
        >
          {props.busy ? 'Checking…' : 'Check'}
        </button>
        <span className={over ? 'counter over' : 'counter'}>{`${trimmed.length} / ${MAX_INTENT_CHARS}`}</span>
      </div>
      {props.error && (
        <p role="alert" className="error result">
          {props.error}
        </p>
      )}
      {!props.error && props.note && <p className="result">{props.note}</p>}
    </div>
  )
}
