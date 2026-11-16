import { useState } from 'react'
import type { Review } from '../types'

/** Accept or correct a model's explanation. What is saved becomes training data. */
export function ExplanationReview(props: {
  shown: string
  review: Review | undefined
  /** 'you', or the teammate's name */
  by: string
  onAccept: () => void
  onCorrect: (text: string) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const verdict = props.review?.verdict

  if (draft !== null) {
    const text = draft.trim()
    return (
      <div className="review">
        <label htmlFor="correction">Corrected explanation</label>
        <textarea id="correction" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <div className="review-row">
          <button
            type="button"
            className="secondary"
            disabled={text === '' || text.length > 2000}
            onClick={() => {
              props.onCorrect(text)
              setDraft(null)
            }}
          >
            Save correction
          </button>
          <button type="button" className="plain" onClick={() => setDraft(null)}>
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="review review-row">
      {verdict === 'accepted' && <span className="review-state ok">{`Marked correct by ${props.by}.`}</span>}
      {verdict === 'corrected' && <span className="review-state ok">{`Corrected by ${props.by}.`}</span>}
      {verdict !== 'accepted' && (
        <button type="button" className="chip" onClick={props.onAccept}>
          Mark as correct
        </button>
      )}
      <button type="button" className="chip" onClick={() => setDraft(props.shown)}>
        Correct it
      </button>
    </div>
  )
}

/** Confirm or dismiss a flagged mismatch. */
export function MismatchReview(props: {
  review: Review | undefined
  by: string
  onVerdict: (verdict: 'confirmed' | 'dismissed') => void
}) {
  const verdict = props.review?.verdict
  const who = props.by === 'you' ? 'You' : props.by
  return (
    <div className="review review-row">
      {verdict === 'confirmed' && <span className="review-state">{`${who} confirmed this as a real issue.`}</span>}
      {verdict === 'dismissed' && <span className="review-state">{`${who} marked this as not an issue.`}</span>}
      <button type="button" className="chip" aria-pressed={verdict === 'confirmed'} onClick={() => props.onVerdict('confirmed')}>
        Real issue
      </button>
      <button type="button" className="chip" aria-pressed={verdict === 'dismissed'} onClick={() => props.onVerdict('dismissed')}>
        Not an issue
      </button>
    </div>
  )
}
