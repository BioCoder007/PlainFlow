import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, type MockInstance, vi } from 'vitest'
import * as api from '../api'
import { IntentBox } from '../components/IntentBox'
import { FileViewPage } from '../pages/FileViewPage'
import { MODEL, SOURCE } from './fixtures'

vi.mock('@xyflow/react', () => import('./flowStub'))

const box = () => screen.getByLabelText('What should this do?')
const check = () => screen.getByRole('button', { name: 'Check' })

it('disables Check for blank text and for text over 1000 characters', () => {
  render(<IntentBox onCheck={() => {}} busy={false} error={null} note={null} />)
  expect(check()).toBeDisabled()
  expect(screen.getByText('0 / 1000')).toBeInTheDocument()
  fireEvent.change(box(), { target: { value: '   ' } })
  expect(check()).toBeDisabled()
  fireEvent.change(box(), { target: { value: 'x'.repeat(1000) } })
  expect(check()).toBeEnabled()
  fireEvent.change(box(), { target: { value: 'x'.repeat(1001) } })
  expect(check()).toBeDisabled()
  expect(screen.getByText('1001 / 1000')).toBeInTheDocument()
})

it('passes the trimmed text to onCheck', async () => {
  const onCheck = vi.fn()
  render(<IntentBox onCheck={onCheck} busy={false} error={null} note={null} />)
  await userEvent.type(box(), '  sums the list  ')
  await userEvent.click(check())
  expect(onCheck).toHaveBeenCalledWith('sums the list')
})

it('disables the button while a check is running', () => {
  render(<IntentBox onCheck={() => {}} busy={true} error={null} note={null} />)
  expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled()
})

it('shows an error under the box', () => {
  render(<IntentBox onCheck={() => {}} busy={false} error="The check could not be completed. Try again." note={null} />)
  expect(screen.getByRole('alert')).toHaveTextContent('The check could not be completed. Try again.')
})

// -- wired into the file view ------------------------------------------------

let checkIntent: MockInstance<typeof api.checkIntent>

beforeEach(() => {
  vi.spyOn(api, 'getRepo').mockResolvedValue({ repo_id: 'r1', model: MODEL })
  vi.spyOn(api, 'getSource').mockResolvedValue(SOURCE)
  vi.spyOn(api, 'explain').mockResolvedValue({ s1: 'E1', s2: 'E2', s3: 'E3', s4: 'E4', s5: 'E5', s6: 'E6' })
  checkIntent = vi.spyOn(api, 'checkIntent')
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

const stepNode = (id: string) => within(screen.getByTestId(`node-${id}`)).getByTitle(/./)

async function runCheck(text = 'sums every number') {
  await userEvent.type(await screen.findByLabelText('What should this do?'), text)
  await userEvent.click(check())
}

it('flags the returned steps on the flow', async () => {
  checkIntent.mockResolvedValue([{ step_id: 's4', reason: 'Skips negative numbers.' }])
  renderFile()
  await runCheck()
  await waitFor(() => expect(stepNode('s4')).toHaveClass('flagged'))
  expect(stepNode('s5')).not.toHaveClass('flagged')
  expect(checkIntent).toHaveBeenCalledWith('r1', 'app.py::total', 'sums every number')
  expect(screen.getByText('1 step may differ from your description. Select it to see why.')).toBeInTheDocument()
})

it("shows 'Possible mismatch: <reason>' when a flagged step is selected", async () => {
  checkIntent.mockResolvedValue([{ step_id: 's4', reason: 'Skips negative numbers.' }])
  renderFile()
  await runCheck()
  await waitFor(() => expect(stepNode('s4')).toHaveClass('flagged'))
  await userEvent.click(screen.getByTestId('node-s4'))
  expect(screen.getByText('Possible mismatch: Skips negative numbers.')).toBeInTheDocument()
  expect(screen.getByText('E4')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('node-s5'))
  expect(screen.queryByText(/Possible mismatch/)).not.toBeInTheDocument()
})

it('shows the no-differences line with its caveat when the list is empty', async () => {
  checkIntent.mockResolvedValue([])
  renderFile()
  await runCheck()
  expect(
    await screen.findByText('No differences found. This is not a guarantee that the code is correct.'),
  ).toBeInTheDocument()
})

it('clears the text and the flags when another function is selected', async () => {
  checkIntent.mockResolvedValue([{ step_id: 's1', reason: 'Wrong start value.' }])
  renderFile()
  await runCheck()
  await waitFor(() => expect(stepNode('s1')).toHaveClass('flagged'))
  await userEvent.click(screen.getByRole('button', { name: 'fmt' }))
  await waitFor(() => expect(screen.getAllByTestId(/^node-/)).toHaveLength(1))
  expect(stepNode('s1')).not.toHaveClass('flagged')
  expect(box()).toHaveValue('')
  expect(screen.queryByText(/may differ/)).not.toBeInTheDocument()
})

it("shows the server's message when the check fails", async () => {
  checkIntent.mockRejectedValue(new api.ApiError('The check could not be completed. Try again.'))
  renderFile()
  await runCheck()
  expect(await screen.findByRole('alert')).toHaveTextContent('The check could not be completed. Try again.')
  expect(check()).toBeEnabled()
})
