import {
  Background,
  Controls,
  type Edge,
  Handle,
  MarkerType,
  MiniMap,
  type Node,
  Position,
  ReactFlow,
} from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, getRepo } from '../api'
import { ExportButton } from '../components/ExportButton'
import { ModelButton } from '../components/ModelButton'
import { layoutGraph } from '../layout'
import { useMovable } from '../useMovable'
import { FOLDER_COLORS, INK } from '../theme'
import type { FileNode, RepoModel } from '../types'

const NODE_HEIGHT = 56

function countLabel(file: FileNode): string {
  if (file.parse_error) return 'Could not parse'
  const n = file.functions.length
  return n === 1 ? '1 function' : `${n} functions`
}

/** A colour index per top-level folder; files at the repo root share index 0. */
export function folderTone(path: string): number {
  const slash = path.indexOf('/')
  if (slash === -1) return 0
  let hash = 0
  for (const ch of path.slice(0, slash)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return 1 + (hash % (FOLDER_COLORS.length - 1))
}

function nodeWidth(file: FileNode): number {
  return Math.min(360, Math.max(150, file.path.length * 7.6 + 36))
}

function FileNodeView({ data }: { data: { path: string; count: string; broken: boolean; tone: number } }) {
  return (
    <div className={`file-node${data.broken ? ' broken' : ''}`} data-tone={data.tone}>
      <Handle type="target" position={Position.Left} />
      <span className="file-path">{data.path}</span>
      <span className="file-count">{data.count}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = { file: FileNodeView }
const NO_NODES: Node[] = []

function buildGraph(model: RepoModel): { nodes: Node[]; edges: Edge[] } {
  const sized = model.files.map((f) => ({ id: f.path, width: nodeWidth(f), height: NODE_HEIGHT }))
  const positions = layoutGraph(sized, model.file_edges, 'LR')
  const nodes: Node[] = model.files.map((f, i) => ({
    id: f.path,
    type: 'file',
    position: positions[f.path],
    width: sized[i].width,
    height: NODE_HEIGHT,
    data: { path: f.path, count: countLabel(f), broken: f.parse_error !== null, tone: folderTone(f.path) },
  }))
  const edges: Edge[] = model.file_edges.map((e) => ({
    id: `${e.kind}:${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    markerEnd: { type: MarkerType.ArrowClosed, color: e.kind === 'call' ? '#3d9bff' : '#6b7099' },
    style:
      e.kind === 'call'
        ? { stroke: '#3d9bff', strokeWidth: 1.4, strokeDasharray: '6 4' }
        : { stroke: '#6b7099', strokeWidth: 1.2 },
  }))
  return { nodes, edges }
}

export function RepoMapPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [model, setModel] = useState<RepoModel | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setModel(null)
    setError(null)
    getRepo(id).then(
      (res) => live && setModel(res.model),
      (e) => live && setError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.'),
    )
    return () => {
      live = false
    }
  }, [id])

  const graph = useMemo(() => (model ? buildGraph(model) : null), [model])
  const { nodes, onNodesChange, reset, hasMoved } = useMovable(id, graph?.nodes ?? NO_NODES)

  if (error) {
    return (
      <main className="page-message">
        <p role="alert" className="error">
          {error}
        </p>
        <Link to="/">Start over</Link>
      </main>
    )
  }
  if (!model || !graph) return <main className="page-message">Loading…</main>

  const skipped = model.skipped.length
  return (
    <main className="map-page">
      <header className="bar">
        <Link to="/" className="brand">
          PlainFlow
        </Link>
        <span className="bar-note">
          {model.files.length} {model.files.length === 1 ? 'file' : 'files'} · click a file to open it, drag to move it
        </span>
        <span className="spacer" />
        {hasMoved && (
          <button type="button" className="secondary" onClick={reset}>
            Reset layout
          </button>
        )}
        <ExportButton repoId={id} />
        <ModelButton />
        <span className="legend">
          <span className="swatch solid" /> imports
          <span className="swatch dashed" /> calls
        </span>
      </header>
      <div className="canvas">
        <ReactFlow
          nodes={nodes}
          onNodesChange={onNodesChange}
          nodesDraggable
          edges={graph.edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => navigate(`/repo/${id}/file/${node.id}`)}
          nodesConnectable={false}
          colorMode="dark"
          fitView
        fitViewOptions={{ maxZoom: 1 }}
          minZoom={0.1}
        >
          <Background color={INK.line} gap={22} />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            bgColor={INK.panel}
            maskColor="rgba(18, 19, 31, 0.7)"
            nodeColor={(node) => FOLDER_COLORS[folderTone(node.id)]}
          />
        </ReactFlow>
      </div>
      {skipped > 0 && (
        <details className="skipped">
          <summary>{skipped === 1 ? '1 file was skipped' : `${skipped} files were skipped`}</summary>
          <ul>
            {model.skipped.map((s) => (
              <li key={s.path}>{`${s.path}: ${s.reason}`}</li>
            ))}
          </ul>
        </details>
      )}
    </main>
  )
}
