import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import * as api from '../api'
import { StartPage } from '../pages/StartPage'
import { MODEL } from './fixtures'

function renderStart() {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<StartPage />} />
        <Route path="/repo/:id" element={<div>map page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

it('navigates to the repo map after a successful URL submit', async () => {
  const create = vi.spyOn(api, 'createRepoFromUrl').mockResolvedValue({ repo_id: 'r1', model: MODEL })
  renderStart()
  await userEvent.type(screen.getByLabelText('GitHub repository URL'), 'https://github.com/o/r')
  await userEvent.click(screen.getByRole('button', { name: 'Visualize' }))
  expect(await screen.findByText('map page')).toBeInTheDocument()
  expect(create).toHaveBeenCalledWith('https://github.com/o/r')
})

it("shows the server's error message when ingest fails", async () => {
  vi.spyOn(api, 'createRepoFromUrl').mockRejectedValue(new api.ApiError('Repository not found.'))
  renderStart()
  await userEvent.type(screen.getByLabelText('GitHub repository URL'), 'https://github.com/o/nope')
  await userEvent.click(screen.getByRole('button', { name: 'Visualize' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Repository not found.')
  expect(screen.getByRole('button', { name: 'Visualize' })).toBeEnabled()
})

it('disables the button while the request is running', async () => {
  vi.spyOn(api, 'createRepoFromUrl').mockReturnValue(new Promise(() => {}))
  renderStart()
  await userEvent.type(screen.getByLabelText('GitHub repository URL'), 'https://github.com/o/r')
  await userEvent.click(screen.getByRole('button', { name: 'Visualize' }))
  expect(screen.getByRole('button', { name: 'Reading repository…' })).toBeDisabled()
})

it('does not submit an empty URL', async () => {
  const create = vi.spyOn(api, 'createRepoFromUrl')
  renderStart()
  expect(screen.getByRole('button', { name: 'Visualize' })).toBeDisabled()
  expect(create).not.toHaveBeenCalled()
})

it('uploads a chosen zip and navigates to the map', async () => {
  const create = vi.spyOn(api, 'createRepoFromZip').mockResolvedValue({ repo_id: 'r2', model: MODEL })
  renderStart()
  const file = new File(['zip'], 'repo.zip', { type: 'application/zip' })
  await userEvent.upload(screen.getByLabelText('Upload a zip'), file)
  expect(await screen.findByText('map page')).toBeInTheDocument()
  expect(create).toHaveBeenCalledWith(file)
})
