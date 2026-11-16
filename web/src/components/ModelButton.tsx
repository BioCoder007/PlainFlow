import { type FormEvent, useEffect, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { ApiError, type Detected, detectFromKey, detectLocal, fetchModels, testConnection } from '../api'
import {
  LOCAL_ADDRESSES,
  type LlmSettings,
  loadSettings,
  PROVIDER_LABELS,
  type Provider,
  detectProvider,
  saveSettings,
  serviceName,
  suggestModel,
  subscribe,
} from '../settings'

export function useLlmSettings(): LlmSettings | null {
  return useSyncExternalStore(subscribe, loadSettings, loadSettings)
}

// Model lists already fetched in this session, so reopening the panel or re-pasting a key is instant.
const modelCache = new Map<string, string[]>()

const EMPTY: LlmSettings = { provider: 'anthropic', model: '', apiKey: '', baseUrl: '' }
const NEEDS_ADDRESS: Provider[] = ['local', 'other']

type TestState = { status: 'idle' } | { status: 'running' } | { status: 'ok' } | { status: 'failed'; message: string }

/** Header button showing the model in use; opens the settings panel. */
export function ModelButton() {
  const settings = useLlmSettings()
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="model-button" onClick={() => setOpen(true)}>
        {settings ? `Model: ${settings.model}` : 'Choose AI model'}
      </button>
      {/* In the page body, not the header: the header's blur would shrink a fixed overlay to its own height. */}
      {open &&
        createPortal(
          <SettingsPanel initial={settings ?? EMPTY} hasSaved={settings !== null} onClose={() => setOpen(false)} />,
          document.body,
        )}
    </>
  )
}

function SettingsPanel(props: { initial: LlmSettings; hasSaved: boolean; onClose: () => void }) {
  const [draft, setDraft] = useState<LlmSettings>(props.initial)
  const [test, setTest] = useState<TestState>({ status: 'idle' })
  const [models, setModels] = useState<string[]>([])
  const [lookup, setLookup] = useState<'idle' | 'running' | 'failed'>('idle')
  const [autoNote, setAutoNote] = useState('')
  const [autoModel, setAutoModel] = useState('') // a model name we filled in, not the developer
  const [manual, setManual] = useState(false) // show the provider and address fields
  // Whether the provider is known to match the key. An unrecognised key is never sent to a guessed provider.
  const [trusted, setTrusted] = useState(props.hasSaved)
  const [finding, setFinding] = useState<'idle' | 'running'>('idle')
  const [findError, setFindError] = useState('')

  const needsAddress = NEEDS_ADDRESS.includes(draft.provider)
  const showKey = draft.provider !== 'local'
  const keyOptional = draft.provider === 'other'
  const cleaned: LlmSettings = {
    provider: draft.provider,
    model: draft.model.trim(),
    apiKey: showKey ? draft.apiKey.trim() : '',
    baseUrl: needsAddress ? draft.baseUrl.trim() : '',
  }
  const complete =
    cleaned.model !== '' &&
    (!needsAddress || cleaned.baseUrl !== '') &&
    (!showKey || keyOptional || cleaned.apiKey !== '')

  // Look up the models this key or local server offers, once the details look complete.
  const lookupKey = `${cleaned.provider}|${cleaned.apiKey}|${cleaned.baseUrl}`
  const ready =
    showKey && !keyOptional
      ? trusted && cleaned.apiKey.length >= 20
      : needsAddress
        ? cleaned.baseUrl !== '' && (trusted || draft.provider === 'local')
        : false
  useEffect(() => {
    if (!ready) {
      setModels([])
      setLookup('idle')
      return
    }
    const cached = modelCache.get(lookupKey)
    if (cached) {
      setModels(cached)
      setLookup('idle')
      if (draft.model.trim() === '' || draft.model === autoModel) {
        const pick = suggestModel(cached)
        setAutoModel(pick)
        setDraft((d) => (d.model.trim() === '' || d.model === autoModel ? { ...d, model: pick } : d))
      }
      return
    }
    let stale = false
    setLookup('running')
    const timer = setTimeout(() => {
      fetchModels(cleaned).then(
        (found) => {
          modelCache.set(lookupKey, found)
          if (stale) return
          setModels(found)
          setLookup('idle')
          if (draft.model.trim() === '' || draft.model === autoModel) {
            const pick = suggestModel(found)
            setAutoModel(pick)
            setDraft((d) => (d.model.trim() === '' || d.model === autoModel ? { ...d, model: pick } : d))
          }
        },
        () => {
          if (stale) return
          setModels([])
          setLookup('failed')
        },
      )
    }, 150)
    return () => {
      stale = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lookupKey, ready])

  function applyDetected(found: Detected, apiKey: string) {
    setTrusted(true)
    setFindError('')
    modelCache.set(`${found.provider}|${apiKey}|${found.base_url}`, found.models)
    setModels(found.models)
    const pick = suggestModel(found.models)
    setAutoModel(pick)
    setAutoNote(`Detected ${serviceName(found.provider, found.base_url)}.`)
    change({ provider: found.provider, baseUrl: found.base_url, apiKey, model: pick })
  }

  /** Tries the key against the known services to find the one it belongs to. */
  function findProvider() {
    setFinding('running')
    setFindError('')
    detectFromKey(draft.apiKey.trim()).then(
      (found) => {
        setFinding('idle')
        applyDetected(found, draft.apiKey.trim())
      },
      (e) => {
        setFinding('idle')
        setFindError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')
      },
    )
  }

  /** Looks for Ollama or LM Studio on this computer. */
  function useLocal() {
    setFinding('running')
    setFindError('')
    // Show the local-model fields at once, so the address can be set by hand if the search finds nothing.
    if (draft.provider !== 'local') changeProvider('local')
    detectLocal().then(
      (found) => {
        setFinding('idle')
        applyDetected(found, '')
      },
      (e) => {
        setFinding('idle')
        setFindError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')
      },
    )
  }

  function changeKey(apiKey: string) {
    const found = detectProvider(apiKey)
    setFindError('')
    if (found) setTrusted(true)
    else if (!manual) setTrusted(false)
    if (!found && !manual) setAutoNote('')
    if (found && (found.provider !== draft.provider || found.baseUrl !== draft.baseUrl)) {
      setAutoNote(`Detected ${serviceName(found.provider, found.baseUrl)}.`)
      change({
        apiKey,
        provider: found.provider,
        baseUrl: found.baseUrl,
        ...(draft.model === autoModel ? { model: '' } : {}),
      })
    } else {
      change({ apiKey })
    }
  }

  function change(patch: Partial<LlmSettings>) {
    setDraft((d) => ({ ...d, ...patch }))
    setTest({ status: 'idle' })
  }

  function changeProvider(provider: Provider) {
    setTrusted(true) // chosen by hand
    setAutoNote('')
    change({ provider, baseUrl: provider === 'local' ? LOCAL_ADDRESSES.Ollama : '' })
  }

  function save(event: FormEvent) {
    event.preventDefault()
    if (!complete) return
    saveSettings(cleaned)
    props.onClose()
  }

  function runTest() {
    setTest({ status: 'running' })
    testConnection(cleaned).then(
      () => setTest({ status: 'ok' }),
      (e) =>
        setTest({ status: 'failed', message: e instanceof ApiError ? e.message : 'Something went wrong. Try again.' }),
    )
  }

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="AI model settings">
      <form className="settings" onSubmit={save}>
        <h2>AI model</h2>
        <p className="fine">
          Used for explanations and the intent check. Your settings stay in this browser and are sent only to the
          provider you choose.
        </p>

        {showKey ? (
          <>
            <label htmlFor="llm-key">{keyOptional && manual ? 'API key (optional)' : 'API key'}</label>
            <input
              id="llm-key"
              type="password"
              autoComplete="off"
              value={draft.apiKey}
              onChange={(e) => changeKey(e.target.value)}
              placeholder="Paste your key. PlainFlow finds the provider."
            />
          </>
        ) : (
          <p className="detected">
            {`Using ${serviceName(draft.provider, draft.baseUrl)}. No key needed.`}{' '}
            <button type="button" className="link" onClick={() => changeProvider('anthropic')}>
              Use an API key instead
            </button>
          </p>
        )}
        {showKey && autoNote && <p className="detected">{autoNote}</p>}
        {showKey && !manual && (lookup === 'failed' || (!trusted && draft.apiKey.trim().length >= 20)) && (
          <div className="find">
            <button type="button" className="secondary" disabled={finding === 'running'} onClick={findProvider}>
              {finding === 'running' ? 'Searching…' : 'Find my provider'}
            </button>
            <p className="fine">
              Tries this key with OpenAI, Anthropic, Gemini, Groq, Mistral, DeepSeek, Together, xAI, Cerebras and
              Fireworks to see which one accepts it.
            </p>
          </div>
        )}
        {findError && (
          <p role="alert" className="error">
            {findError}
          </p>
        )}
        <div className="setup-links">
          {showKey && (
            <button type="button" className="link" disabled={finding === 'running'} onClick={useLocal}>
              Use a model on this computer (no key)
            </button>
          )}
          <button type="button" className="link" aria-expanded={manual} onClick={() => setManual((m) => !m)}>
            {manual ? 'Hide manual setup' : 'Set up manually'}
          </button>
        </div>
        {manual && (
          <div className="manual">
        <label htmlFor="llm-provider">Provider</label>
        <select
          id="llm-provider"
          value={draft.provider}
          onChange={(e) => changeProvider(e.target.value as Provider)}
        >
          {(Object.keys(PROVIDER_LABELS) as Provider[]).map((p) => (
            <option key={p} value={p}>
              {PROVIDER_LABELS[p]}
            </option>
          ))}
        </select>

          </div>
        )}
        {needsAddress && (manual || draft.provider === 'local') && (
          <>
            <label htmlFor="llm-address">Endpoint address</label>
            <input
              id="llm-address"
              type="text"
              value={draft.baseUrl}
              onChange={(e) => change({ baseUrl: e.target.value })}
              placeholder="http://localhost:11434/v1"
            />
            {draft.provider === 'local' && (
              <p className="fine">
                Point PlainFlow at your model server: pick Ollama or LM Studio, or type the address it runs on.
              </p>
            )}
            {draft.provider === 'local' && (
              <div className="shortcuts">
                <button type="button" disabled={finding === 'running'} onClick={useLocal}>
                  {finding === 'running' ? 'Searching…' : 'Search this computer'}
                </button>
                {(Object.keys(LOCAL_ADDRESSES) as (keyof typeof LOCAL_ADDRESSES)[]).map((name) => (
                  <button key={name} type="button" onClick={() => change({ baseUrl: LOCAL_ADDRESSES[name] })}>
                    {name}
                  </button>
                ))}
              </div>
            )}
          </>
        )}


        <label htmlFor="llm-model">Model name</label>
        <input
          id="llm-model"
          type="text"
          value={draft.model}
          onChange={(e) => change({ model: e.target.value })}
          list="llm-model-options"
          placeholder={draft.provider === 'local' ? 'The name your local server lists' : "The provider's model id"}
        />
        <datalist id="llm-model-options">
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
        {lookup === 'running' && <p className="fine">Finding the models this key can use…</p>}
        {lookup === 'failed' && (
          <p className="fine">Could not list models. Check the key or address, or type the model name yourself.</p>
        )}
        {models.length > 0 && (
          <p className="fine">
            {models.length === 1 ? '1 model found.' : `${models.length} models found.`} Pick one from the list or type
            a name.
          </p>
        )}

        {test.status === 'ok' && <p className="result ok">Connection works.</p>}
        {test.status === 'failed' && (
          <p role="alert" className="error result">
            {test.message}
          </p>
        )}

        <div className="settings-actions">
          <button type="button" className="secondary" disabled={!complete || test.status === 'running'} onClick={runTest}>
            {test.status === 'running' ? 'Testing…' : 'Test connection'}
          </button>
          <span className="spacer" />
          {props.hasSaved && (
            <button
              type="button"
              className="plain"
              onClick={() => {
                saveSettings(null)
                props.onClose()
              }}
            >
              Remove
            </button>
          )}
          <button type="button" className="plain" onClick={props.onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={!complete}>
            Save
          </button>
        </div>
      </form>
    </div>
  )
}
