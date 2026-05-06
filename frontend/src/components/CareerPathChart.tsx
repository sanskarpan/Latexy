'use client'

/**
 * Career Path Visualization chart (Feature 80).
 *
 * Renders a directed acyclic graph of career roles using SVG + @visx/network.
 * Nodes: role cards colored by state (current / path / target / other).
 * Edges: arrows labeled with avg years + difficulty.
 * Click a node to see its required skills.
 */

import { useMemo, useState } from 'react'
import { Group } from '@visx/group'
import { Text } from '@visx/text'
import type { CareerRoleResponse } from '@/lib/api-client'

// ── Types ─────────────────────────────────────────────────────────────────────

interface NodeData {
  id: string
  title: string
  level: string
  required_skills: string[]
  state: 'current' | 'path' | 'target' | 'other'
}

interface EdgeData {
  from: string
  to: string
  avg_years?: number
  difficulty?: string
}

interface LayoutNode extends NodeData {
  x: number
  y: number
}

interface CareerPathChartProps {
  pathRoles: CareerRoleResponse[]     // ordered path from current → target
  targetRole: CareerRoleResponse | null
  currentRoleTitle?: string
  onNodeClick?: (role: CareerRoleResponse) => void
}

// ── Layout ────────────────────────────────────────────────────────────────────

const NODE_W = 160
const NODE_H = 48
const H_GAP = 220  // horizontal gap between nodes
const V_GAP = 90   // vertical gap when wrapping to next row
const MAX_PER_ROW = 4

function layoutNodes(roles: CareerRoleResponse[]): LayoutNode[] {
  return roles.map((role, i) => {
    const col = i % MAX_PER_ROW
    const row = Math.floor(i / MAX_PER_ROW)
    return {
      id: role.id,
      title: role.title,
      level: role.level,
      required_skills: role.required_skills || [],
      state: 'path' as const,
      x: col * H_GAP + NODE_W / 2,
      y: row * V_GAP + NODE_H / 2,
    }
  })
}

// ── Colors ────────────────────────────────────────────────────────────────────

function nodeColors(state: NodeData['state']) {
  switch (state) {
    case 'current': return { fill: 'rgba(124,58,237,0.15)', stroke: '#7c3aed', text: '#c4b5fd' }
    case 'target':  return { fill: 'rgba(16,185,129,0.15)', stroke: '#10b981', text: '#6ee7b7' }
    case 'path':    return { fill: 'rgba(255,255,255,0.05)', stroke: 'rgba(255,255,255,0.15)', text: '#d4d4d8' }
    default:        return { fill: 'rgba(255,255,255,0.03)', stroke: 'rgba(255,255,255,0.08)', text: '#71717a' }
  }
}

function levelBadgeColor(level: string) {
  const map: Record<string, string> = {
    intern: '#374151', junior: '#1e3a5f', mid: '#1c3748', senior: '#2d3748',
    staff: '#3d2a5c', principal: '#4c1d95', director: '#7c1f39', vp: '#7c1d1d',
    'c-suite': '#7c2d12',
  }
  return map[level] ?? '#27272a'
}

// ── Arrow marker ──────────────────────────────────────────────────────────────

const ARROW_ID = 'career-arrow'

function ArrowMarker() {
  return (
    <defs>
      <marker
        id={ARROW_ID}
        markerWidth="8"
        markerHeight="8"
        refX="7"
        refY="3"
        orient="auto"
      >
        <path d="M0,0 L0,6 L8,3 z" fill="rgba(255,255,255,0.25)" />
      </marker>
    </defs>
  )
}

// ── Edge ──────────────────────────────────────────────────────────────────────

function Edge({
  from, to, isOnPath,
}: {
  from: { x: number; y: number }
  to: { x: number; y: number }
  isOnPath: boolean
}) {
  const dx = to.x - from.x
  const dy = to.y - from.y
  // Control point offset for curves
  const cpx = from.x + dx * 0.5
  const cpy = from.y

  const d = `M${from.x},${from.y} Q${cpx},${cpy} ${to.x},${to.y}`
  return (
    <path
      d={d}
      fill="none"
      stroke={isOnPath ? 'rgba(139,92,246,0.6)' : 'rgba(255,255,255,0.1)'}
      strokeWidth={isOnPath ? 2 : 1}
      strokeDasharray={isOnPath ? undefined : '4,3'}
      markerEnd={`url(#${ARROW_ID})`}
    />
  )
}

// ── Node ──────────────────────────────────────────────────────────────────────

function CareerNode({
  node,
  isSelected,
  onClick,
}: {
  node: LayoutNode
  isSelected: boolean
  onClick: () => void
}) {
  const { fill, stroke, text } = nodeColors(node.state)
  const x = node.x - NODE_W / 2
  const y = node.y - NODE_H / 2

  return (
    <Group onClick={onClick} style={{ cursor: 'pointer' }}>
      <rect
        x={x}
        y={y}
        width={NODE_W}
        height={NODE_H}
        rx={6}
        fill={fill}
        stroke={isSelected ? '#818cf8' : stroke}
        strokeWidth={isSelected ? 2 : 1}
      />
      {/* Level badge */}
      <rect
        x={x + 6}
        y={y + 6}
        width={50}
        height={14}
        rx={3}
        fill={levelBadgeColor(node.level)}
      />
      <text
        x={x + 31}
        y={y + 16}
        textAnchor="middle"
        fontSize={8}
        fill="#94a3b8"
        fontFamily="system-ui"
        fontWeight={600}
      >
        {node.level.toUpperCase()}
      </text>
      {/* Title */}
      <foreignObject x={x + 4} y={y + 24} width={NODE_W - 8} height={NODE_H - 28}>
        <div
          // @ts-ignore — xmlns required for foreignObject
          xmlns="http://www.w3.org/1999/xhtml"
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: text,
            lineHeight: 1.2,
            overflow: 'hidden',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            fontFamily: 'system-ui',
          }}
        >
          {node.title}
        </div>
      </foreignObject>
    </Group>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function CareerPathChart({
  pathRoles,
  targetRole,
  currentRoleTitle,
  onNodeClick,
}: CareerPathChartProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const nodes = useMemo<LayoutNode[]>(() => {
    if (!pathRoles || pathRoles.length === 0) return []
    return layoutNodes(pathRoles).map((n, i) => ({
      ...n,
      state:
        i === 0 ? 'current'
        : i === pathRoles.length - 1 ? 'target'
        : 'path',
    }))
  }, [pathRoles])

  const nodeMap = useMemo(() => {
    const m: Record<string, LayoutNode> = {}
    nodes.forEach((n) => { m[n.id] = n })
    return m
  }, [nodes])

  if (nodes.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center text-[12px] text-zinc-600">
        No path data available.
      </div>
    )
  }

  const rows = Math.ceil(nodes.length / MAX_PER_ROW)
  const svgW = Math.min(nodes.length, MAX_PER_ROW) * H_GAP + NODE_W / 2
  const svgH = rows * V_GAP + NODE_H + 20

  const selectedNode = selectedId ? nodeMap[selectedId] : null

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto rounded-xl border border-white/[0.06] bg-[#0d0d0d] p-4">
        <svg width={svgW} height={svgH} style={{ overflow: 'visible' }}>
          <ArrowMarker />
          <Group>
            {/* Edges — draw path edges */}
            {nodes.map((node, i) => {
              if (i === nodes.length - 1) return null
              const next = nodes[i + 1]
              return (
                <Edge
                  key={`edge-${i}`}
                  from={{ x: node.x + NODE_W / 2, y: node.y }}
                  to={{ x: next.x - NODE_W / 2, y: next.y }}
                  isOnPath
                />
              )
            })}
            {/* Nodes */}
            {nodes.map((node) => (
              <CareerNode
                key={node.id}
                node={node}
                isSelected={selectedId === node.id}
                onClick={() => {
                  setSelectedId(selectedId === node.id ? null : node.id)
                  const role = pathRoles.find((r) => r.id === node.id)
                  if (role && onNodeClick) onNodeClick(role)
                }}
              />
            ))}
          </Group>
        </svg>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-[10px] text-zinc-600">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-violet-500" />Current role
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-white/20" />Path
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />Target role
        </span>
      </div>

      {/* Selected node detail */}
      {selectedNode && (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-[11px]">
          <div className="mb-1 font-semibold text-zinc-200">{selectedNode.title}</div>
          <div className="mb-2 text-zinc-600">
            {selectedNode.level} · {pathRoles.find((r) => r.id === selectedNode.id)?.industry?.replace(/_/g, ' ')}
          </div>
          {selectedNode.required_skills.length > 0 && (
            <>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-700">
                Required skills
              </div>
              <div className="flex flex-wrap gap-1">
                {selectedNode.required_skills.map((s) => (
                  <span
                    key={s}
                    className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-zinc-400"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
