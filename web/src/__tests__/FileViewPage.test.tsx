import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, type MockInstance, vi } from 'vitest'
import * as api from '../api'
import { FileViewPage } from '../pages/FileViewPage'
import type { Depth, RepoModel } from '../types'
import { MODEL, SCRIPT_MODEL, SOURCE } from './fixtures'

vi.mock('@xyflow/react', () => import('./flowStub'))

let explain: MockInstance<typeof api.explain>
let explainLine: MockInstance<typeof api.explainLine>

beforeEach(() => {
  explainLine = vi
    .spyOn(api, 'explainLine')
    .mockImplementation(async (_id: string, _fn: string, line: number, depth: Depth) => `${depth} line ${line} \`t\``)
  explain = vi.spyOn(api, 'explain').mockImplementation(async (_id: string, fnId: string, depth: Depth) => {
    const fn = MODEL.files.flatMap((f) => f.functions).find((f) => f.id === fnId)
    return Object.fromEntries((fn?.steps ?? []).map((s) => [s.id, `${depth} ${fnId} ${s.id}`]))
  })
})

function renderFile(entry = '/repo/r1/file/app.py', model: RepoModel = MODEL, source = SOURCE) {
  vi.spyOn(api, 'getRepo').mockResolvedValue({ repo_id: 'r1', model })
  vi.spyOn(api, 'getSource').mockResolvedValue(source)
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/repo/:id/file/*" element={<FileViewPage />} />
        <Route path="/repo/:id" element={<div>map page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

it('selects the first function and requests its explanations', async () => {
  renderFile()
  expect(await screen.findByRole('button', { name: 'total' })).toHaveAttribute('aria-current', 'true')
  expect(screen.getByRole('button', { name: 'fmt' })).toHaveAttribute('aria-current', 'false')
  await waitFor(() => expect(explain).toHaveBeenCalledWith('r1', 'app.py::total', 'developer'))
  expect(screen.getAllByTestId(/^node-/)).toHaveLength(6)
  expect(screen.getByTestId('edge-s3-s4')).toHaveTextContent('true')
})

it("shows a step's explanation and highlights its lines when the step is clicked", async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  expect(await screen.findByText('developer app.py::total s5')).toBeInTheDocument()
  expect(screen.getByTestId('line-8')).toHaveClass('highlighted')
  expect(screen.getByTestId('line-7')).not.toHaveClass('highlighted')
  expect(within(screen.getByTestId('node-s5')).getByText('t += util.fix(x)').closest('.step-node')).toHaveClass(
    'selected',
  )
})

it('selects the innermost step when a code line is clicked', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('line-6'))
  expect(await screen.findByText('developer app.py::total s3')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('line-5'))
  expect(await screen.findByText('developer app.py::total s2')).toBeInTheDocument()
})

it('selects nothing when a line outside every step is clicked', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('line-1'))
  expect(await screen.findByText('Select a step in the flow or a line of code.')).toBeInTheDocument()
  expect(screen.getByTestId('line-1')).not.toHaveClass('highlighted')
})

it('re-requests explanations when depth changes and keeps the selected step', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  await screen.findByText('developer app.py::total s5')
  expect(screen.getByRole('button', { name: 'Developer' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Beginner' }))
  expect(await screen.findByText('beginner app.py::total s5')).toBeInTheDocument()
  expect(explain).toHaveBeenCalledWith('r1', 'app.py::total', 'beginner')
  expect(screen.getByTestId('line-8')).toHaveClass('highlighted')
})

it("shows 'Explaining…' while waiting and a retry button on failure", async () => {
  let fail: (e: Error) => void = () => {}
  explain.mockImplementationOnce(() => new Promise((_, reject) => (fail = reject)))
  renderFile()
  expect(await screen.findByText('Explaining…')).toBeInTheDocument()
  fail(new api.ApiError('The server could not be reached.'))
  expect(await screen.findByRole('alert')).toHaveTextContent('The server could not be reached.')
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await userEvent.click(screen.getByTestId('node-s1'))
  expect(await screen.findByText('developer app.py::total s1')).toBeInTheDocument()
  expect(explain).toHaveBeenCalledTimes(2)
})

it("lists resolved calls as links and unresolved calls as text marked '(unresolved)'", async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  expect(await screen.findByText('x.strip (unresolved)')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'util.fix' })).toHaveAttribute(
    'href',
    '/repo/r1/file/pkg/util.py?fn=pkg%2Futil.py%3A%3Afix',
  )
  expect(screen.queryByRole('link', { name: 'fmt' })).not.toBeInTheDocument()
})

it('opens the function named in the fn query parameter', async () => {
  renderFile('/repo/r1/file/app.py?fn=app.py%3A%3Afmt')
  expect(await screen.findByRole('button', { name: 'fmt' })).toHaveAttribute('aria-current', 'true')
  await waitFor(() => expect(explain).toHaveBeenCalledWith('r1', 'app.py::fmt', 'developer'))
})

it('switches function from the outline and clears the selected step', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('node-s5'))
  await userEvent.click(screen.getByRole('button', { name: 'fmt' }))
  await waitFor(() => expect(explain).toHaveBeenCalledWith('r1', 'app.py::fmt', 'developer'))
  expect(await screen.findByText('Select a step in the flow or a line of code.')).toBeInTheDocument()
  expect(screen.getAllByTestId(/^node-/)).toHaveLength(1)
})

it('shows the <module> function for a script file', async () => {
  renderFile('/repo/r1/file/run.py', SCRIPT_MODEL, 'x = 1\nprint(x)')
  expect(await screen.findByRole('button', { name: '<module>' })).toHaveAttribute('aria-current', 'true')
})

it('says so when the file could not be parsed, and still shows its code', async () => {
  renderFile('/repo/r1/file/broken.py', MODEL, 'def f(:\n    pass')
  expect(await screen.findByText('Could not parse this file: line 1: invalid syntax')).toBeInTheDocument()
  expect(screen.getByTestId('line-1')).toHaveTextContent('def f(:')
  expect(explain).not.toHaveBeenCalled()
})

it('says so when the file is not in the repo', async () => {
  renderFile('/repo/r1/file/nope.py')
  expect(await screen.findByRole('alert')).toHaveTextContent('File not found.')
})

it('links back to the map', async () => {
  renderFile()
  await userEvent.click(await screen.findByRole('link', { name: 'Back to map' }))
  expect(await screen.findByText('map page')).toBeInTheDocument()
})

// final review I7
it('does not request explanations for the old file while following a link to another file', async () => {
  renderFile('/repo/r1/file/app.py?fn=app.py%3A%3Afmt')
  await userEvent.click(await screen.findByTestId('node-s1'))
  await userEvent.click(await screen.findByRole('link', { name: 'util.fix' }))
  await waitFor(() => expect(explain).toHaveBeenCalledWith('r1', 'pkg/util.py::fix', 'developer'))
  expect(explain).not.toHaveBeenCalledWith('r1', 'app.py::total', 'developer')
})


it('explains a single clicked line, highlights only that line, and steps to the next one', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('line-5'))
  expect(await screen.findByText('Line 5')).toBeInTheDocument()
  expect(await screen.findByText(/developer line 5/)).toBeInTheDocument()
  expect(screen.getByText('t', { selector: 'code' })).toBeInTheDocument()
  expect(explainLine).toHaveBeenCalledWith('r1', 'app.py::total', 5, 'developer')
  expect(screen.getByTestId('line-5')).toHaveClass('highlighted')
  expect(screen.getByTestId('line-6')).not.toHaveClass('highlighted')
  await userEvent.click(screen.getByRole('button', { name: 'Next line' }))
  expect(await screen.findByText(/developer line 6/)).toBeInTheDocument()
  expect(screen.getByTestId('line-6')).toHaveClass('highlighted')
})

it('selecting a step in the flow goes back to the whole step', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('line-8'))
  expect(await screen.findByText('Line 8')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('node-s2'))
  expect(screen.queryByText('Line 8')).not.toBeInTheDocument()
  expect(screen.getByTestId('line-5')).toHaveClass('highlighted')
  expect(screen.getByTestId('line-8')).toHaveClass('highlighted')
})

it('asks the model once per line and depth', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('line-4'))
  await screen.findByText(/developer line 4/)
  await userEvent.click(screen.getByTestId('line-5'))
  await screen.findByText(/developer line 5/)
  await userEvent.click(screen.getByTestId('line-4'))
  await screen.findByText(/developer line 4/)
  expect(explainLine).toHaveBeenCalledTimes(2)
})

it('shift-click selects a range and explains it as one piece', async () => {
  explainLine.mockImplementation(async (_i, _f, line, depth, end) => `${depth} range ${line}-${end ?? line}`)
  renderFile()
  await userEvent.click(await screen.findByTestId('line-5'))
  await screen.findByText(/developer range 5-5/)
  const user = userEvent.setup()
  await user.keyboard('{Shift>}')
  await user.click(screen.getByTestId('line-8'))
  await user.keyboard('{/Shift}')
  expect(await screen.findByText('Lines 5 to 8')).toBeInTheDocument()
  expect(await screen.findByText(/developer range 5-8/)).toBeInTheDocument()
  expect(explainLine).toHaveBeenLastCalledWith('r1', 'app.py::total', 5, 'developer', 8)
  for (const n of [5, 6, 7, 8]) expect(screen.getByTestId(`line-${n}`)).toHaveClass('highlighted')
  expect(screen.getByTestId('line-9')).not.toHaveClass('highlighted')
})

it('explains the whole function with one click', async () => {
  explainLine.mockImplementation(async (_i, _f, line, depth, end) => `${depth} range ${line}-${end ?? line}`)
  renderFile()
  await userEvent.click(await screen.findByRole('button', { name: 'Explain whole function' }))
  expect(await screen.findByText('Whole function, lines 3 to 9')).toBeInTheDocument()
  expect(await screen.findByText(/developer range 3-9/)).toBeInTheDocument()
})

it('does not show a step error while a line is selected', async () => {
  explain.mockRejectedValue(new api.ApiError('The AI model request failed: too large'))
  renderFile()
  await userEvent.click(await screen.findByTestId('line-6'))
  expect(await screen.findByText(/developer line 6/)).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  await userEvent.click(screen.getByTestId('node-s3'))
  expect(await screen.findByRole('alert')).toHaveTextContent('too large')
})

it('clicking a line in another function switches to that function and explains the line', async () => {
  renderFile()
  await userEvent.click(await screen.findByTestId('line-12'))
  await waitFor(() => expect(screen.getByRole('button', { name: 'fmt' })).toHaveAttribute('aria-current', 'true'))
  expect(await screen.findByText('Line 12')).toBeInTheDocument()
  expect(explainLine).toHaveBeenCalledWith('r1', 'app.py::fmt', 12, 'developer')
  expect(screen.getByTestId('line-12')).toHaveClass('highlighted')
})

it('owningFunction prefers the innermost function over the module', async () => {
  const { owningFunction } = await import('../pages/FileViewPage')
  const f = (qualname: string, line_start: number, line_end: number) =>
    ({ id: qualname, name: qualname, qualname, line_start, line_end, steps: [], edges: [], calls: [] })
  const fns = [f('<module>', 1, 50), f('A.run', 10, 30), f('A.run.inner', 15, 20)]
  expect(owningFunction(fns, 17)?.qualname).toBe('A.run.inner')
  expect(owningFunction(fns, 12)?.qualname).toBe('A.run')
  expect(owningFunction(fns, 40)?.qualname).toBe('<module>')
  expect(owningFunction(fns.slice(1), 40)).toBeNull()
})

it('dragging across lines selects the range and explains it', async () => {
  const { fireEvent } = await import('@testing-library/react')
  explainLine.mockImplementation(async (_i, _f, line, depth, end) => `${depth} range ${line}-${end ?? line}`)
  renderFile()
  fireEvent.mouseDown(await screen.findByTestId('line-8'))
  fireEvent.mouseEnter(screen.getByTestId('line-6'))
  fireEvent.mouseEnter(screen.getByTestId('line-5'))
  expect(screen.getByTestId('line-6')).toHaveClass('highlighted')
  fireEvent.mouseUp(window)
  expect(await screen.findByText('Lines 5 to 8')).toBeInTheDocument()
  expect(await screen.findByText(/developer range 5-8/)).toBeInTheDocument()
  expect(explainLine).toHaveBeenCalledTimes(1)
})
