import type { StepKind } from './types'

/** One colour per kind of step. The same values are in index.css as --c-<kind>. */
export const KIND_COLOR: Record<StepKind, string> = {
  block: '#3d9bff',
  branch: '#ff8a1f',
  loop: '#a56bff',
  return: '#1fe08a',
  raise: '#ff3d5e',
  try: '#12d6e0',
  with: '#ff5cc8',
}

export const KIND_ORDER: StepKind[] = ['block', 'branch', 'loop', 'return', 'raise', 'try', 'with']

export const KIND_LABEL: Record<StepKind, string> = {
  block: 'Statements',
  branch: 'Decision',
  loop: 'Loop',
  return: 'Return',
  raise: 'Raise',
  try: 'Try',
  with: 'With',
}

export type EdgeTone = 'true' | 'false' | 'loop' | 'exit' | 'except' | 'plain'

export const EDGE_COLOR: Record<EdgeTone, string> = {
  true: '#1fe08a',
  false: '#ff3d5e',
  loop: '#a56bff',
  exit: '#9a9dbd',
  except: '#ff3d5e',
  plain: '#6b7099',
}

export function edgeTone(label: string | null): EdgeTone {
  return label === 'true' || label === 'false' || label === 'loop' || label === 'exit' || label === 'except'
    ? label
    : 'plain'
}

/** Colours for file groups on the repo map: index 0 is for files at the repo root. */
export const FOLDER_COLORS = ['#9a9dbd', '#3d9bff', '#a56bff', '#1fe08a', '#ff8a1f', '#ff5cc8', '#12d6e0']

export const INK = { panel: '#1a1c2c', text: '#e8e9f5', muted: '#9a9dbd', line: '#2f3350' }
