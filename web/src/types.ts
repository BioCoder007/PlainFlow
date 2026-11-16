// TypeScript mirror of the engine's repo model (cve_engine.models).
export type StepKind = 'block' | 'branch' | 'loop' | 'return' | 'raise' | 'try' | 'with'

export interface Step {
  id: string
  kind: StepKind
  label: string
  line_start: number
  line_end: number
}

export interface StepEdge {
  source: string
  target: string
  label: string | null
}

export interface CallRef {
  name: string
  line: number
  target: string | null
  /** True when the name is bound inside the caller, so it is never linked. */
  local?: boolean
}

export interface ImportRef {
  module: string
  line: number
  target: string | null
  names: Record<string, string>
}

export interface FunctionNode {
  id: string
  name: string
  qualname: string
  line_start: number
  line_end: number
  steps: Step[]
  edges: StepEdge[]
  calls: CallRef[]
}

export interface FileNode {
  path: string
  line_count: number
  functions: FunctionNode[]
  imports: ImportRef[]
  parse_error: string | null
}

export interface FileEdge {
  source: string
  target: string
  kind: 'import' | 'call'
}

export interface SkippedFile {
  path: string
  reason: string
}

export interface RepoModel {
  files: FileNode[]
  file_edges: FileEdge[]
  skipped: SkippedFile[]
}

export interface Mismatch {
  step_id: string
  reason: string
}

export type Depth = 'beginner' | 'developer'

export interface RepoResponse {
  repo_id: string
  model: RepoModel
}

/** A human verdict on a model's explanation or flagged mismatch (cve_engine.export). */
export interface Review {
  type: 'explanation' | 'mismatch'
  reviewed_at: string
  file: string
  function: string
  step: { id: string; kind: StepKind; line_start: number; line_end: number; code: string }
  verdict: 'accepted' | 'corrected' | 'confirmed' | 'dismissed'
  reviewer?: string | null
  depth?: Depth
  model_explanation?: string
  final_explanation?: string
  intent?: string
  model_reason?: string
}

export interface ReviewBody {
  type: 'explanation' | 'mismatch'
  function_id: string
  step_id: string
  verdict: Review['verdict']
  depth?: Depth
  explanation?: string
  corrected?: string
  intent?: string
  reason?: string
}

export interface ReviewSummary {
  total: number
  explanations: number
  mismatches: number
}

export interface ImportResult {
  added: number
  updated: number
  kept: number
  conflicts: number
  skipped: number
}
