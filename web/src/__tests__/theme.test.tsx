import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import * as api from '../api'
import { FileViewPage } from '../pages/FileViewPage'
import { folderTone, RepoMapPage } from '../pages/RepoMapPage'
import { MODEL, SOURCE } from './fixtures'

vi.mock('@xyflow/react', () => import('./flowStub'))

beforeEach(() => {
  vi.spyOn(api, 'getRepo').mockResolvedValue({ repo_id: 'r1', model: MODEL })
  vi.spyOn(api, 'getSource').mockResolvedValue(SOURCE)
  vi.spyOn(api, 'explain').mockResolvedValue({ s1: 'E1', s2: 'E2', s3: 'E3', s4: 'E4', s5: 'E5', s6: 'E6' })
})

function renderAt(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/repo/:id" element={<RepoMapPage />} />
        <Route path="/repo/:id/file/*" element={<FileViewPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

it('shows a colour key for the kinds of step in this function only', async () => {
  renderAt('/repo/r1/file/app.py')
  const key = await screen.findByRole('list', { name: 'Step colours' })
  expect(within(key).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
    'Statements',
    'Decision',
    'Loop',
    'Return',
  ])
})

it('names the selected step by kind and lines above its explanation', async () => {
  renderAt('/repo/r1/file/app.py')
  await userEvent.click(await screen.findByTestId('node-s3'))
  expect(await screen.findByText('Decision, line 6')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('node-s2'))
  expect(await screen.findByText('Loop, lines 5 to 8')).toBeInTheDocument()
})

it("tints the highlighted code lines with the step's colour", async () => {
  renderAt('/repo/r1/file/app.py')
  await userEvent.click(await screen.findByTestId('node-s6'))
  expect(screen.getByTestId('line-9')).toHaveClass('highlighted', 'kind-return')
})

it('colours edges by what they mean', async () => {
  renderAt('/repo/r1/file/app.py')
  await screen.findByTestId('node-s1')
  expect(screen.getByTestId('edge-s3-s4')).toHaveAttribute('data-tone', 'true')
  expect(screen.getByTestId('edge-s3-s5')).toHaveAttribute('data-tone', 'false')
  expect(screen.getByTestId('edge-s2-s3')).toHaveAttribute('data-tone', 'loop')
  expect(screen.getByTestId('edge-s1-s2')).toHaveAttribute('data-tone', 'plain')
})

it('gives files in the same top folder the same colour, and root files their own', async () => {
  expect(folderTone('pkg/a.py')).toBe(folderTone('pkg/sub/b.py'))
  expect(folderTone('app.py')).toBe(folderTone('setup.py'))
  expect(folderTone('pkg/a.py')).not.toBe(folderTone('app.py'))
  renderAt('/repo/r1')
  const node = within(await screen.findByTestId('node-pkg/util.py')).getByText('pkg/util.py').closest('.file-node')
  expect(node).toHaveAttribute('data-tone', String(folderTone('pkg/util.py')))
})
