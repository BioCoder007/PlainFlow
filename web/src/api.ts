import { headersFor, type LlmSettings, llmHeaders, reviewerHeader } from './settings'
import type { Depth, ImportResult, Mismatch, RepoResponse, Review, ReviewBody, ReviewSummary } from './types'

const BASE: string = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? '' : 'http://localhost:8000')

/** An error whose message is safe to show to the user. */
export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, init)
  } catch {
    throw new ApiError('The server could not be reached. Check that it is running.')
  }
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail
    throw new ApiError(typeof detail === 'string' ? detail : 'Something went wrong. Try again.')
  }
  return body as T
}

function postJson<T>(path: string, payload: unknown, extraHeaders: Record<string, string> = {}): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
    body: JSON.stringify(payload),
  })
}

export function createRepoFromUrl(url: string): Promise<RepoResponse> {
  return postJson('/api/repos', { github_url: url })
}

export function createRepoFromZip(file: File): Promise<RepoResponse> {
  const form = new FormData()
  form.append('file', file)
  return request('/api/repos', { method: 'POST', body: form })
}

export function getRepo(id: string): Promise<RepoResponse> {
  return request(`/api/repos/${encodeURIComponent(id)}`)
}

export async function getSource(id: string, path: string): Promise<string> {
  const res = await request<{ source: string }>(
    `/api/repos/${encodeURIComponent(id)}/source?path=${encodeURIComponent(path)}`,
  )
  return res.source
}

export async function explain(id: string, functionId: string, depth: Depth): Promise<Record<string, string>> {
  const res = await postJson<{ explanations: Record<string, string> }>(
    `/api/repos/${encodeURIComponent(id)}/explain`,
    { function_id: functionId, depth },
    llmHeaders(),
  )
  return res.explanations
}

/** A short explanation of one line of a function, or of the range line..endLine as one piece of logic. */
export async function explainLine(
  id: string,
  functionId: string,
  line: number,
  depth: Depth,
  endLine?: number,
): Promise<string> {
  const res = await postJson<{ explanation: string }>(
    `/api/repos/${encodeURIComponent(id)}/explain-line`,
    { function_id: functionId, line, end_line: endLine ?? line, depth },
    llmHeaders(),
  )
  return res.explanation
}

export async function checkIntent(id: string, functionId: string, intent: string): Promise<Mismatch[]> {
  const res = await postJson<{ mismatches: Mismatch[] }>(
    `/api/repos/${encodeURIComponent(id)}/intent`,
    { function_id: functionId, intent },
    llmHeaders(),
  )
  return res.mismatches
}

/** Sends one small request with the given settings. Rejects with the provider's error. */
export async function testConnection(settings: LlmSettings): Promise<void> {
  await postJson<{ ok: boolean }>('/api/llm/test', {}, headersFor(settings))
}

export interface Detected {
  name: string
  provider: LlmSettings['provider']
  base_url: string
  models: string[]
}

/** Finds which service an API key belongs to by trying it against the known services. */
export function detectFromKey(apiKey: string): Promise<Detected> {
  return postJson<Detected>('/api/llm/detect', {}, { 'X-LLM-Key': apiKey })
}

/** Finds Ollama or LM Studio running on this computer. */
export function detectLocal(): Promise<Detected> {
  return postJson<Detected>('/api/llm/detect-local', {}, {})
}

/** The model ids the given key or local server offers. */
export async function fetchModels(settings: LlmSettings): Promise<string[]> {
  const res = await postJson<{ models: string[] }>('/api/llm/models', {}, headersFor(settings))
  return res.models
}

/** Saves a human verdict. Reviewing the same step again replaces the earlier one. */
export async function saveReview(id: string, body: ReviewBody): Promise<Review> {
  const res = await postJson<{ review: Review }>(`/api/repos/${encodeURIComponent(id)}/reviews`, body, {
    ...llmHeaders(),
    ...reviewerHeader(),
  })
  return res.review
}

export async function getReviews(id: string, functionId: string): Promise<Review[]> {
  const res = await request<{ reviews: Review[] }>(
    `/api/repos/${encodeURIComponent(id)}/reviews?function_id=${encodeURIComponent(functionId)}`,
  )
  return res.reviews
}

export function getReviewSummary(): Promise<ReviewSummary> {
  return request('/api/reviews/summary')
}

export const exportUrls = {
  trainingRecords: `${BASE}/api/export/training?format=records`,
  trainingChat: `${BASE}/api/export/training?format=chat`,
  onboarding: (id: string) => `${BASE}/api/repos/${encodeURIComponent(id)}/export/onboarding`,
}

/** Merges a teammate's full-records export into this machine's reviews. */
export function importReviews(file: File): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  return request('/api/reviews/import', { method: 'POST', body: form })
}
