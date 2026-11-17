import { type ChangeEvent, type FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, createRepoFromUrl, createRepoFromZip } from '../api'
import type { RepoResponse } from '../types'

export function StartPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(job: () => Promise<RepoResponse>) {
    setBusy(true)
    setError(null)
    try {
      const { repo_id } = await job()
      navigate(`/repo/${repo_id}`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')
      setBusy(false)
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (url.trim() && !busy) void run(() => createRepoFromUrl(url.trim()))
  }

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file && !busy) void run(() => createRepoFromZip(file))
  }

  return (
    <main className="start">
      <section className="start-form-side">
        <p className="brand-mark">PlainFlow</p>
        <h1>Read any Python repo as a flow you can follow</h1>
        <p className="lede">
          Every function becomes a diagram built from the code itself, with each step explained in plain English beside
          the lines it covers.
        </p>
        <form onSubmit={onSubmit} className="start-form">
          <label htmlFor="repo-url">GitHub repository URL</label>
          <div className="row">
            <input
              id="repo-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/owner/repo"
              disabled={busy}
            />
            <button type="submit" className="primary" disabled={busy || !url.trim()}>
              {busy ? 'Reading repository…' : 'Visualize'}
            </button>
          </div>
        </form>
        <div className="upload">
          <label htmlFor="repo-zip">Upload a zip</label>
          <input id="repo-zip" type="file" accept=".zip,application/zip" onChange={onFile} disabled={busy} />
        </div>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="start-note">
          <p>
            <strong>No setup needed for the map and flow diagrams.</strong> They work as soon as you open a repo.
          </p>
          <p>
            <strong>Explanations need an AI model.</strong> After opening a repo, click <em>Choose AI model</em> and paste
            an API key. A free start: create a Google Gemini key at{' '}
            <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
              aistudio.google.com/apikey
            </a>
            . Or use a model on this computer with Ollama or LM Studio, with no key.
          </p>
        </div>
        <p className="fine">
          Python only, up to 3000 files or 50 MB of Python. Your code is read, never run, and stays on this computer.
        </p>
      </section>
      <HeroFlow />
    </main>
  )
}

/** A small worked example: one function as a flow, and the same steps in plain English. */
function HeroFlow() {
  return (
    <section className="hero" aria-label="Example: a function shown as a flow with plain-English steps">
      <svg viewBox="0 0 420 340" className="hero-flow" aria-hidden="true">
        <g className="trace">
          <path className="t1 plain" d="M150 47 V83" />
          <path className="t2 loop" d="M150 117 V152" />
          <path className="t3 true" d="M150 228 V263" />
          <path className="t4 plain" d="M60 280 H28 V100 H70" />
          <path className="t5 false" d="M236 190 H262 V110 H230" />
          <path className="t6 exit" d="M230 92 H286" />
        </g>
        <g className="n n1 kind-block">
          <rect x="70" y="13" width="160" height="34" rx="7" />
          <text x="150" y="35">total = 0</text>
        </g>
        <g className="n n2 kind-loop">
          <rect x="70" y="83" width="160" height="34" rx="17" />
          <text x="150" y="105">for item in cart:</text>
        </g>
        <g className="n n3 kind-branch">
          <polygon points="150,152 236,190 150,228 64,190" />
          <text x="150" y="194">if item.in_stock:</text>
        </g>
        <g className="n n4 kind-block">
          <rect x="60" y="263" width="180" height="34" rx="7" />
          <text x="150" y="285">total += item.price</text>
        </g>
        <g className="n n5 kind-return">
          <rect x="286" y="75" width="122" height="34" rx="7" />
          <text x="347" y="97">return total</text>
        </g>
        <g className="edge-words">
          <text className="loop" x="158" y="140">loop</text>
          <text className="true" x="158" y="251">true</text>
          <text className="false" x="268" y="155">false</text>
          <text className="exit" x="246" y="85">exit</text>
        </g>
      </svg>
      <ol className="hero-steps">
        <li className="kind-block">Start the total at zero.</li>
        <li className="kind-loop">Go through every item in the cart.</li>
        <li className="kind-branch">Is this item in stock?</li>
        <li className="kind-block">If it is, add its price to the total.</li>
        <li className="kind-return">When the cart is done, hand back the total.</li>
      </ol>
    </section>
  )
}
