import { describe, test, expect } from 'vitest'
import {
  generateTimeline,
  generateSkillBars,
  generateFlowchart,
  generateNetwork,
  type TimelineEntry,
  type SkillBar,
  type FlowNode,
  type FlowEdge,
} from '../tikz-generator'

// ── generateTimeline ──────────────────────────────────────────────────────────

describe('generateTimeline', () => {
  test('output contains tikzpicture delimiters', () => {
    const entries: TimelineEntry[] = [
      { year: '2023', label: 'Started', description: 'New job' },
    ]
    const result = generateTimeline(entries)
    expect(result).toContain('\\begin{tikzpicture}')
    expect(result).toContain('\\end{tikzpicture}')
  })

  test('3 entries produce 3 node[right] occurrences', () => {
    const entries: TimelineEntry[] = [
      { year: '2021', label: 'A', description: '' },
      { year: '2022', label: 'B', description: '' },
      { year: '2023', label: 'C', description: '' },
    ]
    const result = generateTimeline(entries)
    const matches = result.match(/\\node\[right\]/g) ?? []
    expect(matches).toHaveLength(3)
  })

  test('empty entries still produces valid tikzpicture', () => {
    const result = generateTimeline([])
    expect(result).toContain('\\begin{tikzpicture}')
    expect(result).toContain('\\end{tikzpicture}')
  })

  test('year and label appear in output', () => {
    const entries: TimelineEntry[] = [
      { year: '2024', label: 'Promoted', description: 'Senior role' },
    ]
    const result = generateTimeline(entries)
    expect(result).toContain('2024')
    expect(result).toContain('Promoted')
  })

  test('includes required package comment', () => {
    const result = generateTimeline([])
    expect(result).toContain('\\usepackage{tikz}')
  })
})

// ── generateSkillBars ─────────────────────────────────────────────────────────

describe('generateSkillBars', () => {
  test('output contains tikzpicture delimiters', () => {
    const result = generateSkillBars([{ skill: 'Python', level: 8 }])
    expect(result).toContain('\\begin{tikzpicture}')
    expect(result).toContain('\\end{tikzpicture}')
  })

  test('fill width is proportional to level (level 5 = half of max)', () => {
    const result = generateSkillBars([{ skill: 'Go', level: 5 }])
    // Level 5 → fillWidth = (5/10) * 5 = 2.500 cm; rect end = 2.500 + 0.1 = 2.600
    expect(result).toContain('2.600')
  })

  test('level 10 produces maximum fill width (5cm)', () => {
    const result = generateSkillBars([{ skill: 'Rust', level: 10 }])
    // fill rect: (0.1 + 5.0) = 5.100
    expect(result).toContain('5.100')
  })

  test('level 0 produces zero fill (bar starts and ends at same x)', () => {
    const result = generateSkillBars([{ skill: 'Haskell', level: 0 }])
    // fillWidth = 0, fill rect ends at 0.100
    expect(result).toContain('0.100')
  })

  test('skill name appears in output', () => {
    const result = generateSkillBars([{ skill: 'TypeScript', level: 9 }])
    expect(result).toContain('TypeScript')
  })
})

// ── generateFlowchart ─────────────────────────────────────────────────────────

describe('generateFlowchart', () => {
  const nodes: FlowNode[] = [
    { id: 'n1', label: 'Start', x: 0, y: 0, shape: 'circle' },
    { id: 'n2', label: 'Decision', x: 2, y: 0, shape: 'diamond' },
    { id: 'n3', label: 'End', x: 4, y: 0, shape: 'rect' },
  ]
  const edges: FlowEdge[] = [
    { from: 'n1', to: 'n2' },
    { from: 'n2', to: 'n3', label: 'Yes' },
  ]

  test('output contains tikzpicture delimiters', () => {
    const result = generateFlowchart(nodes, edges)
    expect(result).toContain('\\begin{tikzpicture}')
    expect(result).toContain('\\end{tikzpicture}')
  })

  test('diamond shape keyword appears for diamond node', () => {
    const result = generateFlowchart(nodes, edges)
    expect(result).toContain('diamond')
  })

  test('circle shape keyword appears for circle node', () => {
    const result = generateFlowchart(nodes, edges)
    expect(result).toContain('circle')
  })

  test('edge arrows are directional (->)', () => {
    const result = generateFlowchart(nodes, edges)
    expect(result).toContain('->')
    expect(result).not.toContain('<->')
  })

  test('edge labels appear in output', () => {
    const result = generateFlowchart(nodes, edges)
    expect(result).toContain('Yes')
  })
})

// ── generateNetwork ───────────────────────────────────────────────────────────

describe('generateNetwork', () => {
  test('network edges are bidirectional (<->)', () => {
    const nodes: FlowNode[] = [
      { id: 'a', label: 'A', x: 0, y: 0, shape: 'circle' },
      { id: 'b', label: 'B', x: 2, y: 0, shape: 'circle' },
    ]
    const edges: FlowEdge[] = [{ from: 'a', to: 'b' }]
    const result = generateNetwork(nodes, edges)
    expect(result).toContain('<->')
  })
})
