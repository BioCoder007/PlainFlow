import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import * as api from '../api'
import { detectProvider, suggestModel } from '../settings'
import { ModelButton } from '../components/ModelButton'
import { FileViewPage } from '../pages/FileViewPage'
import { llmHeaders, loadSettings, saveSettings, subscribe } from '../settings'
import { MODEL, SOURCE } from './fixtures'

vi.mock('@xyflow/react', () => import('./flowStub'))

const OPENAI = { provider: 'openai', model: 'gpt-x', apiKey: 'k-1', baseUrl: '' } as const

beforeEach(() => {
  localStorage.clear()
  saveSettings(null)
})

// -- the store -----------------------------------------------------------------

it('saves and loads settings in this browser', () => {
  expect(loadSettings()).toBeNull()
  saveSettings(OPENAI)
  expect(loadSettings()).toEqual(OPENAI)
  expect(JSON.parse(localStorage.getItem('cve.llm') ?? 'null')).toEqual(OPENAI)
})

it('builds request headers from the saved settings', () => {
  expect(llmHeaders()).toEqual({})
  saveSettings(OPENAI)
  expect(llmHeaders()).toEqual({ 'X-LLM-Provider': 'openai', 'X-LLM-Model': 'gpt-x', 'X-LLM-Key': 'k-1' })
  saveSettings({ provider: 'other', model: 'llama', apiKey: '', baseUrl: 'http://localhost:11434/v1' })
  expect(llmHeaders()).toEqual({
    'X-LLM-Provider': 'other',
    'X-LLM-Model': 'llama',
    'X-LLM-Base-URL': 'http://localhost:11434/v1',
  })
})

it('tells subscribers when settings change and ignores corrupt stored data', () => {
  const seen = vi.fn()
  const stop = subscribe(seen)
  saveSettings(OPENAI)
  expect(seen).toHaveBeenCalledTimes(1)
  stop()
  saveSettings(null)
  expect(seen).toHaveBeenCalledTimes(1)
  localStorage.setItem('cve.llm', '{not json')
  expect(loadSettings()).toBeNull()
})

it('sends the chosen model with explain and intent requests', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async () => new Response(JSON.stringify({ explanations: {}, mismatches: [] })))
  saveSettings(OPENAI)
  await api.explain('r1', 'f', 'developer')
  await api.checkIntent('r1', 'f', 'x')
  for (const call of fetchMock.mock.calls) {
    const headers = new Headers((call[1] as RequestInit).headers)
    expect(headers.get('X-LLM-Provider')).toBe('openai')
    expect(headers.get('X-LLM-Model')).toBe('gpt-x')
    expect(headers.get('X-LLM-Key')).toBe('k-1')
    expect(headers.get('Content-Type')).toBe('application/json')
  }
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

// -- the settings panel ----------------------------------------------------------

async function openPanel() {
  render(<ModelButton />)
  await userEvent.click(screen.getByRole('button', { name: /Choose AI model|Model:/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Set up manually' }))
}

it('shows which model is in use on the button', async () => {
  render(<ModelButton />)
  expect(screen.getByRole('button', { name: 'Choose AI model' })).toBeInTheDocument()
  act(() => saveSettings(OPENAI))
  expect(await screen.findByRole('button', { name: 'Model: gpt-x' })).toBeInTheDocument()
})

it('saves the provider, model and key, then closes', async () => {
  await openPanel()
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'gemini')
  await userEvent.type(screen.getByLabelText('Model name'), 'gemini-x')
  await userEvent.type(screen.getByLabelText('API key'), 'g-key')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(loadSettings()).toEqual({ provider: 'gemini', model: 'gemini-x', apiKey: 'g-key', baseUrl: '' })
  expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument()
})

it('requires a model and a key before saving', async () => {
  await openPanel()
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Model name'), 'm')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('API key'), 'k')
  expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
})

it('asks for an endpoint address only for Other, where the key is optional', async () => {
  await openPanel()
  expect(screen.queryByLabelText('Endpoint address')).not.toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'other')
  await userEvent.type(screen.getByLabelText('Model name'), 'llama')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Endpoint address'), 'http://localhost:11434/v1')
  expect(screen.getByLabelText('API key (optional)')).toHaveValue('')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(loadSettings()).toEqual({
    provider: 'other',
    model: 'llama',
    apiKey: '',
    baseUrl: 'http://localhost:11434/v1',
  })
})

it('opens with the saved settings and can remove them', async () => {
  saveSettings(OPENAI)
  await openPanel()
  expect(screen.getByLabelText('Provider')).toHaveValue('openai')
  expect(screen.getByLabelText('Model name')).toHaveValue('gpt-x')
  expect(screen.getByLabelText('API key')).toHaveValue('k-1')
  await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
  expect(loadSettings()).toBeNull()
})

it('tests the connection with what is typed, before saving', async () => {
  const test = vi.spyOn(api, 'testConnection').mockResolvedValue(undefined)
  await openPanel()
  await userEvent.type(screen.getByLabelText('Model name'), 'gpt-x')
  await userEvent.type(screen.getByLabelText('API key'), 'k-1')
  await userEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(await screen.findByText('Connection works.')).toBeInTheDocument()
  expect(test).toHaveBeenCalledWith({ provider: 'anthropic', model: 'gpt-x', apiKey: 'k-1', baseUrl: '' })
  expect(loadSettings()).toBeNull()
})

it("shows the provider's error when the connection test fails", async () => {
  vi.spyOn(api, 'testConnection').mockRejectedValue(
    new api.ApiError('The AI model request failed: The API key was rejected by the provider.'),
  )
  await openPanel()
  await userEvent.type(screen.getByLabelText('Model name'), 'gpt-x')
  await userEvent.type(screen.getByLabelText('API key'), 'bad')
  await userEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('The API key was rejected by the provider.')
})

// -- in the file view --------------------------------------------------------------

it('asks for explanations again when the model is changed', async () => {
  vi.spyOn(api, 'getRepo').mockResolvedValue({ repo_id: 'r1', model: MODEL })
  vi.spyOn(api, 'getSource').mockResolvedValue(SOURCE)
  const explain = vi
    .spyOn(api, 'explain')
    .mockRejectedValueOnce(new api.ApiError('No AI model is set up. Choose one in Settings.'))
    .mockResolvedValue({ s1: 'E1' })
  render(
    <MemoryRouter initialEntries={['/repo/r1/file/app.py']}>
      <Routes>
        <Route path="/repo/:id/file/*" element={<FileViewPage />} />
      </Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('No AI model is set up. Choose one in Settings.')
  expect(screen.getByRole('button', { name: 'Choose AI model' })).toBeInTheDocument()
  act(() => saveSettings(OPENAI))
  await waitFor(() => expect(explain).toHaveBeenCalledTimes(2))
  await userEvent.click(screen.getByTestId('node-s1'))
  expect(await screen.findByText('E1')).toBeInTheDocument()
})

// -- local models -------------------------------------------------------------------

it('offers a local model with no key and the Ollama address filled in', async () => {
  await openPanel()
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'local')
  expect(screen.getByLabelText('Endpoint address')).toHaveValue('http://localhost:11434/v1')
  expect(screen.queryByLabelText(/API key/)).not.toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Model name'), 'llama3')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(loadSettings()).toEqual({
    provider: 'local',
    model: 'llama3',
    apiKey: '',
    baseUrl: 'http://localhost:11434/v1',
  })
  expect(llmHeaders()).toEqual({
    'X-LLM-Provider': 'local',
    'X-LLM-Model': 'llama3',
    'X-LLM-Base-URL': 'http://localhost:11434/v1',
  })
})

it('fills in the LM Studio address from its shortcut', async () => {
  await openPanel()
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'local')
  await userEvent.click(screen.getByRole('button', { name: 'LM Studio' }))
  expect(screen.getByLabelText('Endpoint address')).toHaveValue('http://localhost:1234/v1')
  await userEvent.click(screen.getByRole('button', { name: 'Ollama' }))
  expect(screen.getByLabelText('Endpoint address')).toHaveValue('http://localhost:11434/v1')
})


it('key prefix identifies the provider', () => {
    expect(detectProvider('sk-ant-abc')?.provider).toBe('anthropic')
    expect(detectProvider('AIzaSyXYZ')?.provider).toBe('gemini')
    expect(detectProvider('AQ.Abcdef')?.provider).toBe('gemini')
    expect(detectProvider('sk-proj-abc')?.provider).toBe('openai')
    expect(detectProvider('sk-or-v1-abc')?.baseUrl).toBe('https://openrouter.ai/api/v1')
    expect(detectProvider('gsk_abc')?.baseUrl).toBe('https://api.groq.com/openai/v1')
    expect(detectProvider('whatever')).toBeNull()
  })
it('suggestModel prefers a small fast model', () => {
    expect(suggestModel(['big-pro', 'gemini-flash', 'x'])).toBe('gemini-flash')
    expect(suggestModel(['a', 'b'])).toBe('a')
    expect(suggestModel(['gemini-pro', 'gpt-4o-mini'])).toBe('gpt-4o-mini')
  expect(suggestModel([])).toBe('')
  })

it('detects the provider from a pasted key and fills in a model from the list', async () => {
  vi.spyOn(api, 'fetchModels').mockResolvedValue(['gemini-2.5-pro', 'gemini-2.5-flash'])
  await openPanel()
  await userEvent.click(screen.getByLabelText('API key'))
  await userEvent.paste('AIza' + 'x'.repeat(30))
  expect(await screen.findByText(/2 models found\./)).toBeInTheDocument()
  expect(screen.getByLabelText('Provider')).toHaveValue('gemini')
  await waitFor(() => expect(screen.getByLabelText('Model name')).toHaveValue('gemini-2.5-flash'))
})


async function openSimplePanel() {
  render(<ModelButton />)
  await userEvent.click(screen.getByRole('button', { name: /Choose AI model|Model:/ }))
}

it('asks only for a key at first, and hides provider and address', async () => {
  await openSimplePanel()
  expect(screen.getByLabelText('API key')).toBeInTheDocument()
  expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Endpoint address')).not.toBeInTheDocument()
})

it('does not send an unrecognised key anywhere until the user asks, then finds the provider', async () => {
  const fetchModels = vi.spyOn(api, 'fetchModels').mockResolvedValue([])
  const detect = vi.spyOn(api, 'detectFromKey').mockResolvedValue({
    name: 'Mistral',
    provider: 'other',
    base_url: 'https://api.mistral.ai/v1',
    models: ['mistral-large', 'mistral-small-mini'],
  })
  await openSimplePanel()
  await userEvent.click(screen.getByLabelText('API key'))
  await userEvent.paste('zz' + 'x'.repeat(30))
  const find = await screen.findByRole('button', { name: 'Find my provider' })
  await new Promise((r) => setTimeout(r, 400))
  expect(fetchModels).not.toHaveBeenCalled()
  await userEvent.click(find)
  expect(await screen.findByText('Detected Mistral.')).toBeInTheDocument()
  expect(detect).toHaveBeenCalledWith('zz' + 'x'.repeat(30))
  expect(screen.getByLabelText('Model name')).toHaveValue('mistral-small-mini')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(loadSettings()).toEqual({
    provider: 'other',
    model: 'mistral-small-mini',
    apiKey: 'zz' + 'x'.repeat(30),
    baseUrl: 'https://api.mistral.ai/v1',
  })
})

it('shows why no provider was found', async () => {
  vi.spyOn(api, 'detectFromKey').mockRejectedValue(new api.ApiError('No known provider accepted this key.'))
  await openSimplePanel()
  await userEvent.click(screen.getByLabelText('API key'))
  await userEvent.paste('zz' + 'x'.repeat(30))
  await userEvent.click(await screen.findByRole('button', { name: 'Find my provider' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('No known provider accepted this key.')
})

it('finds a model server on this computer with one click', async () => {
  vi.spyOn(api, 'detectLocal').mockResolvedValue({
    name: 'Ollama',
    provider: 'local',
    base_url: 'http://localhost:11434/v1',
    models: ['qwen2.5-coder'],
  })
  await openSimplePanel()
  await userEvent.click(screen.getByRole('button', { name: 'Use a model on this computer (no key)' }))
  expect(await screen.findByText(/Using Ollama on this computer\. No key needed\./)).toBeInTheDocument()
  expect(screen.getByLabelText('Model name')).toHaveValue('qwen2.5-coder')
  expect(screen.queryByLabelText('API key')).not.toBeInTheDocument()
})


it('lets the user point at a local model server by hand when the search finds nothing', async () => {
  vi.spyOn(api, 'detectLocal').mockRejectedValue(new api.ApiError('No local model server was found.'))
  vi.spyOn(api, 'fetchModels').mockResolvedValue(['my-model'])
  await openSimplePanel()
  await userEvent.click(screen.getByRole('button', { name: 'Use a model on this computer (no key)' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('No local model server was found.')
  const address = screen.getByLabelText('Endpoint address')
  expect(screen.getByRole('button', { name: 'Ollama' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'LM Studio' })).toBeInTheDocument()
  await userEvent.clear(address)
  await userEvent.type(address, 'http://192.168.1.20:8080/v1')
  await waitFor(() => expect(screen.getByLabelText('Model name')).toHaveValue('my-model'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(loadSettings()?.baseUrl).toBe('http://192.168.1.20:8080/v1')
})
