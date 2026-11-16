import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import * as api from '../api'
import { RepoMapPage } from '../pages/RepoMapPage'
import { MODEL } from './fixtures'

vi.mock('@xyflow/react', () => import('./flowStub'))

function renderMap(model = MODEL) {
  vi.spyOn(api, 'getRepo').mockResolvedValue({ repo_id: 'r1', model })
  render(
    <MemoryRouter initialEntries={['/repo/r1']}>
      <Routes>
        <Route path="/repo/:id" element={<RepoMapPage />} />
        <Route path="/repo/:id/file/*" element={<div>file view</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

it('renders one node per file with its function count', async () => {
  renderMap()
  const app = await screen.findByTestId('node-app.py')
  expect(within(app).getByText('app.py')).toBeInTheDocument()
  expect(within(app).getByText('2 functions')).toBeInTheDocument()
  expect(within(screen.getByTestId('node-pkg/util.py')).getByText('1 function')).toBeInTheDocument()
  expect(screen.getAllByTestId(/^node-/)).toHaveLength(3)
})

it("marks a file with a parse error as 'Could not parse'", async () => {
  renderMap()
  const broken = await screen.findByTestId('node-broken.py')
  expect(within(broken).getByText('Could not parse')).toBeInTheDocument()
})

it('draws import edges solid and call edges dashed', async () => {
  renderMap()
  await screen.findByTestId('node-app.py')
  const dashed = screen.getAllByTestId('edge-app.py-pkg/util.py').map((e) => e.getAttribute('data-dashed'))
  expect(dashed.sort()).toEqual(['no', 'yes'])
})

it('navigates to the file view when a file node is clicked', async () => {
  renderMap()
  await userEvent.click(await screen.findByTestId('node-pkg/util.py'))
  expect(await screen.findByText('file view')).toBeInTheDocument()
})

it('shows the skipped-files line only when files were skipped', async () => {
  renderMap({ ...MODEL, skipped: [{ path: 'bad.py', reason: 'not UTF-8' }] })
  expect(await screen.findByText('1 file was skipped')).toBeInTheDocument()
  expect(screen.getByText('bad.py: not UTF-8')).toBeInTheDocument()
})

it('shows no skipped-files line when nothing was skipped', async () => {
  renderMap()
  await screen.findByTestId('node-app.py')
  expect(screen.queryByText(/skipped/)).not.toBeInTheDocument()
})

it('shows the error message when the repo cannot be loaded', async () => {
  vi.spyOn(api, 'getRepo').mockRejectedValue(new api.ApiError('Repository not found. It may have expired.'))
  render(
    <MemoryRouter initialEntries={['/repo/r1']}>
      <Routes>
        <Route path="/repo/:id" element={<RepoMapPage />} />
      </Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('Repository not found. It may have expired.')
})
