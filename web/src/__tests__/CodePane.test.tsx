import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CodePane } from '../components/CodePane'

const SRC = ['"""Doc that is', 'long and has from in it.', '"""', 'import os  # and a comment', 'x = "return"'].join('\n')

let scroll: ReturnType<typeof vi.fn>
const original = Element.prototype.scrollIntoView

beforeEach(() => {
  scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll as unknown as typeof original
})
afterEach(() => {
  Element.prototype.scrollIntoView = original
})

function classesIn(line: number): string[] {
  return [...screen.getByTestId(`line-${line}`).querySelectorAll('.src span')].map((s) => s.className)
}

it('keeps the text of every line unchanged', () => {
  render(<CodePane source={SRC} highlight={null} focusLine={null} onLineClick={() => {}} />)
  SRC.split('\n').forEach((text, i) => {
    expect(screen.getByTestId(`line-${i + 1}`).querySelector('.src')?.textContent).toBe(text)
  })
})

it('colours a multi-line docstring as a string, not as keywords', () => {
  render(<CodePane source={SRC} highlight={null} focusLine={null} onLineClick={() => {}} />)
  expect(classesIn(1)).toEqual(['tok-str'])
  expect(classesIn(2)).toEqual(['tok-str'])
  expect(classesIn(3)).toEqual(['tok-str'])
})

it('colours keywords, comments and strings on ordinary lines', () => {
  render(<CodePane source={SRC} highlight={null} focusLine={null} onLineClick={() => {}} />)
  expect(classesIn(4)).toEqual(['tok-kw', 'tok-com'])
  expect(classesIn(5)).toEqual(['tok-str'])
})

it('reports the clicked line number', async () => {
  const onLineClick = vi.fn()
  render(<CodePane source={SRC} highlight={null} focusLine={null} onLineClick={onLineClick} />)
  await userEvent.click(screen.getByTestId('line-4'))
  expect(onLineClick).toHaveBeenCalledWith(4, false)
})

it('scrolls to the focus line when it changes', () => {
  const { rerender } = render(<CodePane source={SRC} highlight={null} focusLine={2} onLineClick={() => {}} />)
  expect(scroll.mock.contexts.at(-1)).toBe(screen.getByTestId('line-2'))
  rerender(<CodePane source={SRC} highlight={null} focusLine={5} onLineClick={() => {}} />)
  expect(scroll.mock.contexts.at(-1)).toBe(screen.getByTestId('line-5'))
})

it('scrolls to the first highlighted line', () => {
  render(<CodePane source={SRC} highlight={{ start: 4, end: 5 }} focusLine={1} onLineClick={() => {}} />)
  expect(scroll.mock.contexts.at(-1)).toBe(screen.getByTestId('line-4'))
})
