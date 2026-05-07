'use client'

/**
 * TikZ / Diagram Visual Editor — Feature 84D
 *
 * Tabs: Timeline | Skill Bars | Flowchart | Network
 * Each tab provides a GUI to compose diagrams; live TikZ preview updates
 * automatically. "Insert into Document" pushes the code to the LaTeX editor.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Clock,
  BarChart2,
  GitBranch,
  Network,
  Plus,
  Trash2,
  Copy,
  Code2,
  ChevronUp,
  ChevronDown,
  Check,
  Loader2,
} from 'lucide-react'
import Editor from '@monaco-editor/react'
import {
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Controls,
  type Connection,
  type EdgeChange,
  type Node,
  type NodeChange,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  generateTimeline,
  generateSkillBars,
  generateFlowchart,
  generateNetwork,
  type TimelineEntry,
  type SkillBar,
  type FlowNode,
  type FlowEdge,
} from '@/lib/tikz/tikz-generator'

type TabId = 'timeline' | 'skill-bars' | 'flowchart' | 'network'

interface Props {
  onInsert: (code: string) => void
  /** Called when user clicks "Preview Diagram" (84E) */
  onPreview?: (tikzCode: string) => void
}

// ── Defaults ──────────────────────────────────────────────────────────────────

const DEFAULT_TIMELINE: TimelineEntry[] = [
  { year: '2022', label: 'Started Role', description: 'Joined Acme Corp as SWE' },
  { year: '2023', label: 'Promotion', description: 'Senior Software Engineer' },
  { year: '2024', label: 'Lead', description: 'Tech lead for Platform team' },
]

const DEFAULT_SKILLS: SkillBar[] = [
  { skill: 'TypeScript', level: 9 },
  { skill: 'Python', level: 8 },
  { skill: 'Rust', level: 6 },
  { skill: 'Go', level: 7 },
]

const DEFAULT_FLOW_NODES: Node[] = [
  { id: 'a', position: { x: 0, y: 0 }, data: { label: 'Start', shape: 'circle' }, type: 'default' },
  { id: 'b', position: { x: 200, y: 0 }, data: { label: 'Process', shape: 'rect' }, type: 'default' },
  { id: 'c', position: { x: 200, y: 120 }, data: { label: 'Decision?', shape: 'diamond' }, type: 'default' },
  { id: 'd', position: { x: 400, y: 60 }, data: { label: 'End', shape: 'circle' }, type: 'default' },
]

const DEFAULT_FLOW_EDGES: Edge[] = [
  { id: 'e1', source: 'a', target: 'b' },
  { id: 'e2', source: 'b', target: 'c' },
  { id: 'e3', source: 'c', target: 'd', label: 'Yes' },
]

// ── Helper sub-components ────────────────────────────────────────────────────

function TabBtn({
  id,
  active,
  icon: Icon,
  label,
  onClick,
}: {
  id: TabId
  active: boolean
  icon: React.ElementType
  label: string
  onClick: () => void
}) {
  return (
    <button
      key={id}
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[11px] font-medium transition ${
        active ? 'bg-violet-500/20 text-violet-300' : 'text-zinc-500 hover:text-zinc-300'
      }`}
    >
      <Icon size={11} />
      {label}
    </button>
  )
}

// ── Timeline Tab ──────────────────────────────────────────────────────────────

function TimelineTab({
  entries,
  onChange,
}: {
  entries: TimelineEntry[]
  onChange: (e: TimelineEntry[]) => void
}) {
  const add = () =>
    onChange([...entries, { year: String(new Date().getFullYear()), label: 'New entry', description: '' }])
  const remove = (i: number) => onChange(entries.filter((_, j) => j !== i))
  const update = (i: number, patch: Partial<TimelineEntry>) => {
    const next = [...entries]
    next[i] = { ...next[i], ...patch }
    onChange(next)
  }
  const move = (i: number, dir: -1 | 1) => {
    const next = [...entries]
    const j = i + dir
    if (j < 0 || j >= next.length) return
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-2 overflow-y-auto">
      {entries.map((e, i) => (
        <div
          key={i}
          className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3"
        >
          <div className="mb-2 flex items-center gap-1">
            <button onClick={() => move(i, -1)} className="rounded p-0.5 text-zinc-600 hover:text-zinc-300">
              <ChevronUp size={11} />
            </button>
            <button onClick={() => move(i, 1)} className="rounded p-0.5 text-zinc-600 hover:text-zinc-300">
              <ChevronDown size={11} />
            </button>
            <span className="ml-auto">
              <button onClick={() => remove(i)} className="rounded p-0.5 text-zinc-700 hover:text-red-400">
                <Trash2 size={11} />
              </button>
            </span>
          </div>
          <div className="grid grid-cols-[70px_1fr] gap-2">
            <input
              value={e.year}
              onChange={(ev) => update(i, { year: ev.target.value })}
              placeholder="Year"
              className={inputCls}
            />
            <input
              value={e.label}
              onChange={(ev) => update(i, { label: ev.target.value })}
              placeholder="Label"
              className={inputCls}
            />
          </div>
          <textarea
            value={e.description}
            onChange={(ev) => update(i, { description: ev.target.value })}
            placeholder="Description (optional)"
            rows={2}
            className={`mt-2 w-full resize-none ${inputCls}`}
          />
        </div>
      ))}
      <button onClick={add} className={addBtnCls}>
        <Plus size={11} /> Add entry
      </button>
    </div>
  )
}

// ── Skill Bars Tab ────────────────────────────────────────────────────────────

function SkillBarsTab({
  skills,
  onChange,
}: {
  skills: SkillBar[]
  onChange: (s: SkillBar[]) => void
}) {
  const add = () => onChange([...skills, { skill: 'New Skill', level: 5 }])
  const remove = (i: number) => onChange(skills.filter((_, j) => j !== i))
  const update = (i: number, patch: Partial<SkillBar>) => {
    const next = [...skills]
    next[i] = { ...next[i], ...patch }
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-2 overflow-y-auto">
      {skills.map((s, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            value={s.skill}
            onChange={(e) => update(i, { skill: e.target.value })}
            placeholder="Skill name"
            className={`flex-1 ${inputCls}`}
          />
          <div className="flex items-center gap-1.5">
            <input
              type="range"
              min={0}
              max={10}
              step={1}
              value={s.level}
              onChange={(e) => update(i, { level: Number(e.target.value) })}
              className="w-20 accent-violet-500"
            />
            <span className="w-5 text-center text-[10px] tabular-nums text-zinc-400">{s.level}</span>
          </div>
          <button onClick={() => remove(i)} className="text-zinc-700 hover:text-red-400">
            <Trash2 size={11} />
          </button>
        </div>
      ))}
      <button onClick={add} className={addBtnCls}>
        <Plus size={11} /> Add skill
      </button>
    </div>
  )
}

// ── Flow Canvas (Flowchart & Network) ─────────────────────────────────────────

type ShapeType = 'rect' | 'diamond' | 'circle'

function FlowCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  bidirectional,
}: {
  nodes: Node[]
  edges: Edge[]
  onNodesChange: (c: NodeChange[]) => void
  onEdgesChange: (c: EdgeChange[]) => void
  onConnect: (c: Connection) => void
  bidirectional: boolean
}) {
  const [nextShape, setNextShape] = useState<ShapeType>('rect')

  const addNode = () => {
    const id = `node_${Date.now()}`
    const newNode: Node = {
      id,
      position: { x: Math.random() * 300, y: Math.random() * 200 },
      data: { label: 'New', shape: nextShape },
      type: 'default',
    }
    onNodesChange([{ type: 'add', item: newNode }])
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-zinc-500">Add:</span>
        {(['rect', 'diamond', 'circle'] as ShapeType[]).map((s) => (
          <button
            key={s}
            onClick={() => setNextShape(s)}
            className={`rounded px-2 py-0.5 text-[9px] font-medium transition ${
              nextShape === s
                ? 'bg-violet-500/20 text-violet-300 ring-1 ring-violet-400/30'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {s}
          </button>
        ))}
        <button onClick={addNode} className="ml-auto flex items-center gap-1 rounded bg-violet-500/15 px-2 py-0.5 text-[9px] text-violet-300 ring-1 ring-violet-400/20 hover:bg-violet-500/25">
          <Plus size={9} /> Add node
        </button>
      </div>
      <div className="h-[240px] rounded-lg border border-white/[0.06] bg-zinc-950 overflow-hidden">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
          colorMode="dark"
        >
          <Background color="#444" gap={16} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {bidirectional && (
        <p className="text-[9px] text-zinc-600">Network mode: all edges are bidirectional.</p>
      )}
    </div>
  )
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const inputCls =
  'rounded border border-white/[0.06] bg-black/30 px-2 py-1 text-[11px] text-zinc-200 outline-none focus:border-violet-500/30 w-full'

const addBtnCls =
  'flex items-center gap-1 rounded border border-dashed border-white/[0.08] px-3 py-1.5 text-[10px] text-zinc-600 transition hover:border-violet-400/30 hover:text-violet-300'

// ── Main component ────────────────────────────────────────────────────────────

export default function TikZEditor({ onInsert, onPreview }: Props) {
  const [tab, setTab] = useState<TabId>('timeline')
  const [timeline, setTimeline] = useState<TimelineEntry[]>(DEFAULT_TIMELINE)
  const [skills, setSkills] = useState<SkillBar[]>(DEFAULT_SKILLS)
  const [flowNodes, setFlowNodes] = useState<Node[]>(DEFAULT_FLOW_NODES)
  const [flowEdges, setFlowEdges] = useState<Edge[]>(DEFAULT_FLOW_EDGES)
  const [netNodes, setNetNodes] = useState<Node[]>(DEFAULT_FLOW_NODES.slice(0, 3))
  const [netEdges, setNetEdges] = useState<Edge[]>(DEFAULT_FLOW_EDGES.slice(0, 2))
  const [copied, setCopied] = useState(false)
  const [previewing, setPreviewing] = useState(false)

  // Convert ReactFlow nodes/edges → generator types
  const toFlowNodes = (rfNodes: Node[]): FlowNode[] =>
    rfNodes.map((n) => ({
      id: n.id,
      label: String(n.data.label ?? n.id),
      x: parseFloat((n.position.x / 80).toFixed(2)),
      y: parseFloat((-n.position.y / 60).toFixed(2)),
      shape: (n.data.shape as FlowNode['shape']) ?? 'rect',
    }))

  const toFlowEdges = (rfEdges: Edge[]): FlowEdge[] =>
    rfEdges.map((e) => ({
      from: e.source,
      to: e.target,
      label: typeof e.label === 'string' ? e.label : undefined,
    }))

  // Compute live TikZ code
  const tikzCode = useMemo(() => {
    switch (tab) {
      case 'timeline':
        return generateTimeline(timeline)
      case 'skill-bars':
        return generateSkillBars(skills)
      case 'flowchart':
        return generateFlowchart(toFlowNodes(flowNodes), toFlowEdges(flowEdges))
      case 'network':
        return generateNetwork(toFlowNodes(netNodes), toFlowEdges(netEdges))
    }
  }, [tab, timeline, skills, flowNodes, flowEdges, netNodes, netEdges])

  // ReactFlow callbacks
  const onFlowNodesChange = useCallback(
    (changes: NodeChange[]) => setFlowNodes((nds) => applyNodeChanges(changes, nds)),
    [],
  )
  const onFlowEdgesChange = useCallback(
    (changes: EdgeChange[]) => setFlowEdges((eds) => applyEdgeChanges(changes, eds)),
    [],
  )
  const onFlowConnect = useCallback(
    (connection: Connection) => setFlowEdges((eds) => addEdge(connection, eds)),
    [],
  )

  const onNetNodesChange = useCallback(
    (changes: NodeChange[]) => setNetNodes((nds) => applyNodeChanges(changes, nds)),
    [],
  )
  const onNetEdgesChange = useCallback(
    (changes: EdgeChange[]) => setNetEdges((eds) => applyEdgeChanges(changes, eds)),
    [],
  )
  const onNetConnect = useCallback(
    (connection: Connection) => setNetEdges((eds) => addEdge(connection, eds)),
    [],
  )

  const handleCopy = () => {
    navigator.clipboard.writeText(tikzCode).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const handlePreview = async () => {
    if (!onPreview) return
    setPreviewing(true)
    try {
      await onPreview(tikzCode)
    } finally {
      setPreviewing(false)
    }
  }

  const tabs: { id: TabId; label: string; icon: React.ElementType }[] = [
    { id: 'timeline', label: 'Timeline', icon: Clock },
    { id: 'skill-bars', label: 'Skill Bars', icon: BarChart2 },
    { id: 'flowchart', label: 'Flowchart', icon: GitBranch },
    { id: 'network', label: 'Network', icon: Network },
  ]

  return (
    <div className="flex h-full flex-col gap-0 overflow-hidden">
      {/* Tab strip */}
      <div className="flex shrink-0 gap-0.5 border-b border-white/[0.05] bg-black/10 px-2 py-1.5">
        {tabs.map((t) => (
          <TabBtn
            key={t.id}
            id={t.id}
            active={tab === t.id}
            icon={t.icon}
            label={t.label}
            onClick={() => setTab(t.id)}
          />
        ))}
      </div>

      {/* Diagram editor area */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === 'timeline' && (
          <TimelineTab entries={timeline} onChange={setTimeline} />
        )}
        {tab === 'skill-bars' && (
          <SkillBarsTab skills={skills} onChange={setSkills} />
        )}
        {tab === 'flowchart' && (
          <FlowCanvas
            nodes={flowNodes}
            edges={flowEdges}
            onNodesChange={onFlowNodesChange}
            onEdgesChange={onFlowEdgesChange}
            onConnect={onFlowConnect}
            bidirectional={false}
          />
        )}
        {tab === 'network' && (
          <FlowCanvas
            nodes={netNodes}
            edges={netEdges}
            onNodesChange={onNetNodesChange}
            onEdgesChange={onNetEdgesChange}
            onConnect={onNetConnect}
            bidirectional={true}
          />
        )}
      </div>

      {/* Live TikZ code preview */}
      <div className="shrink-0 border-t border-white/[0.05]">
        <div className="flex items-center gap-1.5 bg-black/20 px-3 py-1.5">
          <Code2 size={10} className="text-zinc-600" />
          <span className="text-[10px] text-zinc-500">Generated TikZ</span>
        </div>
        <div className="h-[160px]">
          <Editor
            value={tikzCode}
            language="latex"
            theme="vs-dark"
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontSize: 10,
              lineNumbers: 'off',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              overviewRulerLanes: 0,
              folding: false,
              lineDecorationsWidth: 4,
              lineNumbersMinChars: 0,
              padding: { top: 8, bottom: 8 },
            }}
          />
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex shrink-0 items-center gap-2 border-t border-white/[0.05] px-3 py-2">
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 rounded px-2.5 py-1 text-[10px] text-zinc-500 transition hover:text-zinc-300"
        >
          {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} />}
          {copied ? 'Copied!' : 'Copy TikZ'}
        </button>
        {onPreview && (
          <button
            onClick={handlePreview}
            disabled={previewing}
            className="flex items-center gap-1.5 rounded px-2.5 py-1 text-[10px] text-zinc-500 transition hover:text-zinc-300 disabled:opacity-40"
          >
            {previewing ? <Loader2 size={10} className="animate-spin" /> : null}
            Preview
          </button>
        )}
        <button
          onClick={() => onInsert(`\n${tikzCode}\n`)}
          className="ml-auto flex items-center gap-1.5 rounded bg-violet-500/20 px-3 py-1 text-[10px] font-medium text-violet-300 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30"
        >
          Insert into Document
        </button>
      </div>
    </div>
  )
}
