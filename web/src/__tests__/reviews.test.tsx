import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, type MockInstance, vi } from 'vitest'
import * as api from '../api'
import { ExportButton } from '../components/ExportButton'
import { loadReviewer, saveReviewer } from '../settings'
import { FileViewPage } from '../pages/FileViewPage'
import type { Review } from '../types'
import { MODEL, SOURCE } from './fixtures'

vi.mock('@xyflow/react', () => import('./flowStub'))

let saveReview: MockInstance<typeof api.saveReview>

function review(partial: Partial<Review>): Review {
  return {
    type: 'explanation',
    reviewed_at: '2026-11-14T10:00:00+00:00',
    file: 'app.py',
    function: 'total',
    step: { id: 's5', kind: 'block', line_start: 8, line_end: 8, code: '' },
    verdict: 'accepted',
    ...partial,
  } as Review
}

beforeEach(() => {
  localStorage.clear()
  saveReviewer('')
  vi.spyOn(api, 'getRepo').mockResolvedValue({ repo_id: 'r1', model: MODEL })
  vi.spyOn(api, 'getSource').mockResolvedValue(SOURCE)
  vi.spyOn(api, 'explain').mockResolvedValue({
    s1: 'E1', s2: 'E2', s3: 'E3', s4: 'E4', s5: 'E5', s6: 'No explanation available for this step.',
  })
  vi.spyOn(api, 'getReviews').mockResolvedValue([])
  saveReview = vi.spyOn(api, 'saveReview').mockImplementation(async (_id, body) =>
    review({
      type: body.type,
      step: { id: body.step_id, kind: 'block', line_start: 8, line_end: 8, code: '' },
      verdict: body.verdict,
      depth: body.depth,
      final_explanation: body.corrected ?? body.explanation,
      model_explanation: body.explanation,
      intent: body.intent,
      model_reason: body.reason,
    }),
  )
})

function renderFile() {
  render(
    <MemoryRouter initialEntries={['/repo/r1/file/app.py']}>
      <Routes>
        <Route path="/repo/:id/file/*" element={<FileViewPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

it('records an explanation as correct', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  await screen.findByText('E5')
  await userEvent.click(screen.getByRole('button', { name: 'Mark as correct' }))
  expect(saveReview).toHaveBeenCalledWith('r1', {
    type: 'explanation',
    function_id: 'app.py::total',
    step_id: 's5',
    depth: 'developer',
    explanation: 'E5',
    verdict: 'accepted',
  })
  expect(await screen.findByText('Marked correct by you.')).toBeInTheDocument()
})

it('records a corrected explanation and shows the corrected text', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  await screen.findByText('E5')
  await userEvent.click(screen.getByRole('button', { name: 'Correct it' }))
  const box = screen.getByLabelText('Corrected explanation')
  expect(box).toHaveValue('E5')
  await userEvent.clear(box)
  await userEvent.type(box, 'Adds the fixed value of x to the total.')
  await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))
  expect(saveReview).toHaveBeenCalledWith('r1', {
    type: 'explanation',
    function_id: 'app.py::total',
    step_id: 's5',
    depth: 'developer',
    explanation: 'E5',
    verdict: 'corrected',
    corrected: 'Adds the fixed value of x to the total.',
  })
  expect(await screen.findByText('Adds the fixed value of x to the total.')).toBeInTheDocument()
  expect(screen.getByText('Corrected by you.')).toBeInTheDocument()
  expect(screen.queryByText('E5')).not.toBeInTheDocument()
})

it('shows reviews saved earlier for this function', async () => {
  vi.spyOn(api, 'getReviews').mockResolvedValue([
    review({ verdict: 'corrected', depth: 'developer', model_explanation: 'E5', final_explanation: 'Human text.' }),
  ])
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  expect(await screen.findByText('Human text.')).toBeInTheDocument()
  expect(screen.getByText('Corrected by you.')).toBeInTheDocument()
})

it('offers no review for a step the model did not explain', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s6'))
  await screen.findByText('No explanation available for this step.')
  expect(screen.queryByRole('button', { name: 'Mark as correct' })).not.toBeInTheDocument()
})

it('shows the reason when a review cannot be saved', async () => {
  saveReview.mockRejectedValue(new api.ApiError('Repository not found. It may have expired.'))
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  await screen.findByText('E5')
  await userEvent.click(screen.getByRole('button', { name: 'Mark as correct' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Repository not found. It may have expired.')
})

it('records whether a flagged mismatch is a real issue', async () => {
  vi.spyOn(api, 'checkIntent').mockResolvedValue([{ step_id: 's4', reason: 'Skips negative numbers.' }])
  renderFile()
  await userEvent.type(await screen.findByLabelText('What should this do?'), 'sums every number')
  await userEvent.click(screen.getByRole('button', { name: 'Check' }))
  await waitFor(() => expect(screen.getByTestId('node-s4').querySelector('.flagged')).not.toBeNull())
  await userEvent.click(screen.getByTestId('node-s4'))
  await userEvent.click(screen.getByRole('button', { name: 'Real issue' }))
  expect(saveReview).toHaveBeenCalledWith('r1', {
    type: 'mismatch',
    function_id: 'app.py::total',
    step_id: 's4',
    intent: 'sums every number',
    reason: 'Skips negative numbers.',
    verdict: 'confirmed',
  })
  expect(await screen.findByText('You confirmed this as a real issue.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Not an issue' }))
  expect(saveReview).toHaveBeenLastCalledWith('r1', expect.objectContaining({ verdict: 'dismissed' }))
  expect(await screen.findByText('You marked this as not an issue.')).toBeInTheDocument()
})

it('offers the three exports with a count of reviewed items', async () => {
  vi.spyOn(api, 'getReviewSummary').mockResolvedValue({ total: 3, explanations: 2, mismatches: 1 })
  render(<ExportButton repoId="r1" />)
  await userEvent.click(screen.getByRole('button', { name: 'Reviews' }))
  const panel = await screen.findByRole('dialog', { name: 'Reviews' })
  expect(await within(panel).findByText('3 reviewed items: 2 explanations, 1 mismatch.')).toBeInTheDocument()
  const href = (name: string) => within(panel).getByRole('link', { name }).getAttribute('href')
  expect(href('Training data, full records (JSONL)')).toBe('http://localhost:8000/api/export/training?format=records')
  expect(href('Training data, chat format (JSONL)')).toBe('http://localhost:8000/api/export/training?format=chat')
  expect(href('Onboarding guide for this repo (Markdown)')).toBe(
    'http://localhost:8000/api/repos/r1/export/onboarding',
  )
})

it('says so when nothing has been reviewed yet', async () => {
  vi.spyOn(api, 'getReviewSummary').mockResolvedValue({ total: 0, explanations: 0, mismatches: 0 })
  render(<ExportButton repoId="r1" />)
  await userEvent.click(screen.getByRole('button', { name: 'Reviews' }))
  expect(
    await screen.findByText('Nothing reviewed yet. Mark explanations as correct, or correct them, to build your data.'),
  ).toBeInTheDocument()
})

// -- team reviews --------------------------------------------------------------------

it("names the teammate who reviewed a step, and says 'you' for your own", async () => {
  saveReviewer('Amman')
  vi.spyOn(api, 'getReviews').mockResolvedValue([
    review({ verdict: 'accepted', depth: 'developer', reviewer: 'Sara', final_explanation: 'E5' }),
    review({
      verdict: 'corrected',
      depth: 'developer',
      reviewer: 'Amman',
      final_explanation: 'Mine.',
      step: { id: 's1', kind: 'block', line_start: 4, line_end: 4, code: '' },
    }),
  ])
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  expect(await screen.findByText('Marked correct by Sara.')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('node-s1'))
  expect(await screen.findByText('Corrected by you.')).toBeInTheDocument()
})

it('saves your name in this browser and sends it with reviews', async () => {
  vi.spyOn(api, 'getReviewSummary').mockResolvedValue({ total: 0, explanations: 0, mismatches: 0 })
  render(<ExportButton repoId="r1" />)
  await userEvent.click(screen.getByRole('button', { name: 'Reviews' }))
  await userEvent.type(screen.getByLabelText('Your name'), 'Amman Safeer')
  expect(loadReviewer()).toBe('Amman Safeer')

  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async () => new Response(JSON.stringify({ review: review({}) })))
  saveReview.mockRestore()
  await api.saveReview('r1', { type: 'explanation', function_id: 'f', step_id: 's1', verdict: 'accepted' })
  const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers)
  expect(headers.get('X-Reviewer')).toBe('Amman%20Safeer')
})

it("imports a teammate's reviews and reports what changed", async () => {
  vi.spyOn(api, 'getReviewSummary')
    .mockResolvedValueOnce({ total: 1, explanations: 1, mismatches: 0 })
    .mockResolvedValue({ total: 4, explanations: 3, mismatches: 1 })
  const importReviews = vi
    .spyOn(api, 'importReviews')
    .mockResolvedValue({ added: 3, updated: 1, kept: 2, conflicts: 1, skipped: 0 })
  render(<ExportButton repoId="r1" />)
  await userEvent.click(screen.getByRole('button', { name: 'Reviews' }))
  const file = new File(['{}'], 'reviews.jsonl')
  await userEvent.upload(screen.getByLabelText("Import a teammate's reviews"), file)
  expect(importReviews).toHaveBeenCalledWith(file)
  expect(
    await screen.findByText(
      "Added 3, updated 1, kept 2 of yours. 1 differed from a teammate's verdict; the newer one was kept.",
    ),
  ).toBeInTheDocument()
  expect(await screen.findByText('4 reviewed items: 3 explanations, 1 mismatch.')).toBeInTheDocument()
})

it('shows why an import failed', async () => {
  vi.spyOn(api, 'getReviewSummary').mockResolvedValue({ total: 0, explanations: 0, mismatches: 0 })
  vi.spyOn(api, 'importReviews').mockRejectedValue(
    new api.ApiError('No reviews were found in this file. Use a full-records export.'),
  )
  render(<ExportButton repoId="r1" />)
  await userEvent.click(screen.getByRole('button', { name: 'Reviews' }))
  await userEvent.upload(screen.getByLabelText("Import a teammate's reviews"), new File(['x'], 'x.txt'))
  expect(await screen.findByRole('alert')).toHaveTextContent('No reviews were found in this file.')
})
