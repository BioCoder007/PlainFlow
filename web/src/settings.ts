/** The developer's chosen AI model. Kept in this browser only. */
export type Provider = 'anthropic' | 'openai' | 'gemini' | 'local' | 'other'

export interface LlmSettings {
  provider: Provider
  model: string
  apiKey: string
  baseUrl: string
}

export const PROVIDER_LABELS: Record<Provider, string> = {
  anthropic: 'Anthropic (Claude)',
  openai: 'OpenAI',
  gemini: 'Google Gemini',
  local: 'Local model on this computer',
  other: 'Other (OpenAI-compatible service)',
}

export const LOCAL_ADDRESSES = {
  Ollama: 'http://localhost:11434/v1',
  'LM Studio': 'http://localhost:1234/v1',
} as const

/** Services with a fixed address, so a learner sees a name instead of a URL. */
export const SERVICE_NAMES: Record<string, string> = {
  'https://openrouter.ai/api/v1': 'OpenRouter',
  'https://api.groq.com/openai/v1': 'Groq',
  'https://api.mistral.ai/v1': 'Mistral',
  'https://api.deepseek.com/v1': 'DeepSeek',
  'https://api.together.xyz/v1': 'Together',
  'https://api.x.ai/v1': 'xAI',
  'https://api.cerebras.ai/v1': 'Cerebras',
  'https://api.fireworks.ai/inference/v1': 'Fireworks',
  'http://localhost:11434/v1': 'Ollama on this computer',
  'http://localhost:1234/v1': 'LM Studio on this computer',
}

/** A plain name for where requests go. */
export function serviceName(provider: Provider, baseUrl: string): string {
  if (provider === 'local' || provider === 'other') return SERVICE_NAMES[baseUrl.trim()] ?? (baseUrl.trim() || PROVIDER_LABELS[provider])
  return PROVIDER_LABELS[provider]
}

const OTHER = (baseUrl: string) => ({ provider: 'other' as Provider, baseUrl })

/** The provider a key belongs to, from its prefix alone. Null when the prefix is not one we know. */
export function detectProvider(key: string): { provider: Provider; baseUrl: string } | null {
  const k = key.trim()
  if (k.startsWith('sk-ant-')) return { provider: 'anthropic', baseUrl: '' }
  if (k.startsWith('AIza') || k.startsWith('AQ.')) return { provider: 'gemini', baseUrl: '' }
  if (k.startsWith('sk-or-')) return OTHER('https://openrouter.ai/api/v1')
  if (k.startsWith('gsk_')) return OTHER('https://api.groq.com/openai/v1')
  if (k.startsWith('xai-')) return OTHER('https://api.x.ai/v1')
  if (k.startsWith('csk-')) return OTHER('https://api.cerebras.ai/v1')
  if (k.startsWith('fw_')) return OTHER('https://api.fireworks.ai/inference/v1')
  if (k.startsWith('sk-')) return { provider: 'openai', baseUrl: '' }
  return null
}

/** The model to preselect from a list: a small, fast one when there is one. */
export function suggestModel(models: string[]): string {
  return models.find((m) => /haiku|flash|[-_]mini/i.test(m)) ?? models[0] ?? ''
}

const STORAGE_KEY = 'cve.llm'
const listeners = new Set<() => void>()
let memory: LlmSettings | null = null // used when browser storage is unavailable
let cachedRaw: string | null | undefined
let cachedValue: LlmSettings | null = null

function isSettings(value: unknown): value is LlmSettings {
  const v = value as Partial<LlmSettings> | null
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof v.provider === 'string' &&
    v.provider in PROVIDER_LABELS &&
    typeof v.model === 'string' &&
    typeof v.apiKey === 'string' &&
    typeof v.baseUrl === 'string'
  )
}

export function loadSettings(): LlmSettings | null {
  let raw: string | null
  try {
    raw = localStorage.getItem(STORAGE_KEY)
  } catch {
    return memory
  }
  if (raw === cachedRaw) return cachedValue // same object while nothing changed
  cachedRaw = raw
  cachedValue = null
  if (raw !== null) {
    try {
      const parsed: unknown = JSON.parse(raw)
      if (isSettings(parsed)) cachedValue = parsed
    } catch {
      /* corrupt data counts as no settings */
    }
  }
  return cachedValue
}

export function saveSettings(settings: LlmSettings | null): void {
  memory = settings
  try {
    if (settings) localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* storage unavailable: keep it for this page only */
  }
  for (const listener of listeners) listener()
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Headers that tell the local server which model to use for this request. */
export function headersFor(settings: LlmSettings | null): Record<string, string> {
  if (!settings) return {}
  const headers: Record<string, string> = {
    'X-LLM-Provider': settings.provider,
    'X-LLM-Model': settings.model,
  }
  if (settings.apiKey) headers['X-LLM-Key'] = settings.apiKey
  if (settings.baseUrl) headers['X-LLM-Base-URL'] = settings.baseUrl
  return headers
}

export function llmHeaders(): Record<string, string> {
  return headersFor(loadSettings())
}

// -- who is reviewing ------------------------------------------------------------
const REVIEWER_KEY = 'cve.reviewer'
let reviewerMemory = ''

/** The name saved with this person's reviews, so a team can tell whose verdict is whose. */
export function loadReviewer(): string {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? ''
  } catch {
    return reviewerMemory
  }
}

export function saveReviewer(name: string): void {
  reviewerMemory = name
  try {
    if (name) localStorage.setItem(REVIEWER_KEY, name)
    else localStorage.removeItem(REVIEWER_KEY)
  } catch {
    /* storage unavailable: keep it for this page only */
  }
  for (const listener of listeners) listener()
}

/** Percent-encoded so a name in any script is a valid header value. */
export function reviewerHeader(): Record<string, string> {
  const name = loadReviewer().trim()
  return name ? { 'X-Reviewer': encodeURIComponent(name) } : {}
}
