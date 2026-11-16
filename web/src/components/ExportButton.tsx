import { type ChangeEvent, useEffect, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { ApiError, exportUrls, getReviewSummary, importReviews } from '../api'
import { loadReviewer, saveReviewer, subscribe } from '../settings'
import type { ImportResult, ReviewSummary } from '../types'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

function importMessage(r: ImportResult): string {
  let text = `Added ${r.added}, updated ${r.updated}, kept ${r.kept} of yours.`
  if (r.conflicts > 0) text += ` ${r.conflicts} differed from a teammate's verdict; the newer one was kept.`
  if (r.skipped > 0) text += ` ${plural(r.skipped, 'damaged line was', 'damaged lines were')} skipped.`
  return text
}

/** Header button: your name, sharing reviews with teammates, and exports built from reviews. */
export function ExportButton({ repoId }: { repoId?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="model-button" onClick={() => setOpen(true)}>
        Reviews
      </button>
      {/* In the page body, not the header: the header's blur would shrink a fixed overlay to its own height. */}
      {open && createPortal(<ReviewsPanel repoId={repoId} onClose={() => setOpen(false)} />, document.body)}
    </>
  )
}

function ReviewsPanel({ repoId, onClose }: { repoId?: string; onClose: () => void }) {
  const name = useSyncExternalStore(subscribe, loadReviewer, loadReviewer)
  const [summary, setSummary] = useState<ReviewSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [imported, setImported] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let live = true
    getReviewSummary().then(
      (s) => live && setSummary(s),
      (e) => live && setError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.'),
    )
    return () => {
      live = false
    }
  }, [refresh])

  function onImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setError(null)
    setImported(null)
    importReviews(file).then(
      (result) => {
        setImported(importMessage(result))
        setRefresh((n) => n + 1)
      },
      (e) => setError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.'),
    )
  }

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="Reviews">
      <div className="settings">
        <h2>Reviews</h2>
        <p className="fine">
          What your team has checked: explanations marked correct or corrected, and mismatches confirmed or dismissed.
        </p>

        <label htmlFor="reviewer-name">Your name</label>
        <input
          id="reviewer-name"
          type="text"
          value={name}
          maxLength={80}
          onChange={(e) => saveReviewer(e.target.value)}
          placeholder="Saved with each review you make"
        />

        {summary && summary.total === 0 && (
          <p className="result">
            Nothing reviewed yet. Mark explanations as correct, or correct them, to build your data.
          </p>
        )}
        {summary && summary.total > 0 && (
          <p className="result">
            {`${plural(summary.total, 'reviewed item', 'reviewed items')}: ${plural(summary.explanations, 'explanation', 'explanations')}, ${plural(summary.mismatches, 'mismatch', 'mismatches')}.`}
          </p>
        )}

        <h3>Share with your team</h3>
        <p className="fine">
          Send teammates your full-records file, and import theirs here. Where two people reviewed the same step, the
          newer verdict is kept.
        </p>
        <label htmlFor="reviews-import">Import a teammate's reviews</label>
        <input id="reviews-import" type="file" accept=".jsonl,.json,.txt" onChange={onImport} />
        {imported && <p className="result ok">{imported}</p>}
        {error && (
          <p role="alert" className="error result">
            {error}
          </p>
        )}

        <h3>Export</h3>
        <p className="fine">
          Built only from reviewed items. The files include your source code, so treat them as you would the code
          itself.
        </p>
        <ul className="export-list">
          <li>
            <a href={exportUrls.trainingRecords} download>
              Training data, full records (JSONL)
            </a>
            <span>Code, step, model text, verdict and reviewer. Also the file to share with teammates.</span>
          </li>
          <li>
            <a href={exportUrls.trainingChat} download>
              Training data, chat format (JSONL)
            </a>
            <span>Ready-made examples for fine-tuning a model on your approved answers.</span>
          </li>
          {repoId && (
            <li>
              <a href={exportUrls.onboarding(repoId)} download>
                Onboarding guide for this repo (Markdown)
              </a>
              <span>A walkthrough of the reviewed functions for new team members.</span>
            </li>
          )}
        </ul>
        <div className="settings-actions">
          <span className="spacer" />
          <button type="button" className="plain" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
