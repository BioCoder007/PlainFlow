import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ExportButton } from '../components/ExportButton'
import { ModelButton } from '../components/ModelButton'

// The header uses backdrop-filter, which makes a fixed child size itself to the header.
// Dialogs must therefore mount outside it, directly in the page body.
describe('dialogs mount outside the header', () => {
  it('model settings', async () => {
    render(<header className="bar"><ModelButton /></header>)
    await userEvent.click(screen.getByRole('button', { name: /choose ai model/i }))
    const dialog = screen.getByRole('dialog', { name: /ai model settings/i })
    expect(dialog.closest('header')).toBeNull()
    expect(dialog.parentElement).toBe(document.body)
  })

  it('reviews', async () => {
    render(<header className="bar"><ExportButton /></header>)
    await userEvent.click(screen.getByRole('button', { name: 'Reviews' }))
    const dialog = screen.getByRole('dialog', { name: 'Reviews' })
    expect(dialog.closest('header')).toBeNull()
    expect(dialog.parentElement).toBe(document.body)
  })
})
