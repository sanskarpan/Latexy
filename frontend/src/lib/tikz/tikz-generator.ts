/**
 * TikZ / Diagram Code Generator — Feature 84
 *
 * Pure TypeScript functions that produce self-contained TikZ code for each
 * supported diagram type. All outputs are wrapped in a tikzpicture environment
 * and include the required package/library directives as leading comments.
 */

// ── Types ─────────────────────────────────────────────────────────────────────

export type DiagramType = 'timeline' | 'skill-bars' | 'flowchart' | 'network'

export interface TimelineEntry {
  year: string
  label: string
  description: string
}

export interface SkillBar {
  skill: string
  /** 0–10 */
  level: number
}

export interface FlowNode {
  id: string
  label: string
  x: number
  y: number
  shape: 'rect' | 'diamond' | 'circle'
}

export interface FlowEdge {
  from: string
  to: string
  label?: string
  /** true for network (bidirectional) edges */
  bidirectional?: boolean
}

// ── Escape helper ─────────────────────────────────────────────────────────────

/** Escape special LaTeX characters in user-provided strings. */
function esc(s: string): string {
  return s
    .replace(/\\/g, '\\textbackslash{}')
    .replace(/&/g, '\\&')
    .replace(/%/g, '\\%')
    .replace(/\$/g, '\\$')
    .replace(/#/g, '\\#')
    .replace(/_/g, '\\_')
    .replace(/\{/g, '\\{')
    .replace(/\}/g, '\\}')
    .replace(/~/g, '\\textasciitilde{}')
    .replace(/\^/g, '\\textasciicircum{}')
}

// ── 84B · Timeline Generator ──────────────────────────────────────────────────

/**
 * Produces a vertical timeline with tick marks for each entry.
 *
 * Required packages (add to preamble if not present):
 *   \usepackage{tikz}
 *   \usetikzlibrary{positioning}
 */
export function generateTimeline(entries: TimelineEntry[]): string {
  if (entries.length === 0) {
    return [
      '% Requires: \\usepackage{tikz} \\usetikzlibrary{positioning}',
      '\\begin{tikzpicture}',
      '  % No entries',
      '\\end{tikzpicture}',
    ].join('\n')
  }

  const totalHeight = entries.length * 1.6
  const lines: string[] = [
    '% Requires: \\usepackage{tikz} \\usetikzlibrary{positioning}',
    '\\begin{tikzpicture}[every node/.style={font=\\small}]',
    `  \\draw[thick, ->] (0,0) -- (0,-${totalHeight.toFixed(1)});`,
  ]

  entries.forEach((entry, i) => {
    const y = -(i * 1.6 + 0.8)
    const yF = y.toFixed(2)
    const yDesc = (y - 0.45).toFixed(2)
    lines.push(
      `  \\draw (-0.15, ${yF}) -- (0.15, ${yF});`,
      `  \\node[right] at (0.3, ${yF}) {\\textbf{${esc(entry.year)}} --- ${esc(entry.label)}};`,
    )
    if (entry.description.trim()) {
      lines.push(
        `  \\node[right, text width=6cm, text=gray] at (0.3, ${yDesc}) {${esc(entry.description)}};`,
      )
    }
  })

  lines.push('\\end{tikzpicture}')
  return lines.join('\n')
}

// ── 84C · Skill Bars Generator ────────────────────────────────────────────────

const SKILL_BAR_MAX_WIDTH = 5.0 // cm
const SKILL_BAR_HEIGHT = 0.28 // cm
const SKILL_ROW_STEP = 0.7 // cm between rows

/**
 * Produces horizontal skill bars. Level 0–10 maps to 0–5 cm fill width.
 *
 * Required packages:
 *   \usepackage{tikz}
 */
export function generateSkillBars(skills: SkillBar[]): string {
  if (skills.length === 0) {
    return [
      '% Requires: \\usepackage{tikz}',
      '\\begin{tikzpicture}',
      '  % No skills',
      '\\end{tikzpicture}',
    ].join('\n')
  }

  const lines: string[] = ['% Requires: \\usepackage{tikz}', '\\begin{tikzpicture}[font=\\small]']

  skills.forEach((skill, i) => {
    const y = -(i * SKILL_ROW_STEP)
    const yTop = (y + SKILL_BAR_HEIGHT / 2).toFixed(3)
    const yBot = (y - SKILL_BAR_HEIGHT / 2).toFixed(3)
    const level = Math.max(0, Math.min(10, skill.level))
    const fillWidth = ((level / 10) * SKILL_BAR_MAX_WIDTH).toFixed(3)

    lines.push(
      `  % ${esc(skill.skill)}`,
      `  \\node[left, font=\\small] at (0, ${y.toFixed(3)}) {${esc(skill.skill)}};`,
      `  \\fill[gray!20] (0.1, ${yBot}) rectangle (${(SKILL_BAR_MAX_WIDTH + 0.1).toFixed(3)}, ${yTop});`,
      `  \\fill[violet!70] (0.1, ${yBot}) rectangle (${(parseFloat(fillWidth) + 0.1).toFixed(3)}, ${yTop});`,
    )
  })

  lines.push('\\end{tikzpicture}')
  return lines.join('\n')
}

// ── Flowchart / Network Generator ────────────────────────────────────────────

const SHAPE_STYLE: Record<FlowNode['shape'], string> = {
  rect: 'draw, rectangle, minimum width=2cm, minimum height=0.7cm',
  diamond: 'draw, diamond, aspect=2, minimum width=2.2cm, minimum height=0.8cm',
  circle: 'draw, circle, minimum size=1.2cm',
}

/**
 * Produces a flowchart or network diagram using tikz positioning.
 *
 * Required packages:
 *   \usepackage{tikz}
 *   \usetikzlibrary{shapes.geometric, arrows.meta, positioning}
 */
export function generateFlowchart(nodes: FlowNode[], edges: FlowEdge[]): string {
  const header = [
    '% Requires: \\usepackage{tikz}',
    '% \\usetikzlibrary{shapes.geometric, arrows.meta, positioning}',
    '\\begin{tikzpicture}[',
    '  >=Stealth,',
    '  node distance=1.5cm,',
    '  every node/.style={font=\\small},',
    ']',
  ]

  const nodeLines = nodes.map((n) => {
    const style = SHAPE_STYLE[n.shape] ?? SHAPE_STYLE.rect
    return `  \\node[${style}] (${n.id}) at (${n.x.toFixed(2)}, ${n.y.toFixed(2)}) {${esc(n.label)}};`
  })

  const edgeLines = edges.map((e) => {
    const arrow = e.bidirectional ? '<->' : '->'
    const labelPart = e.label ? ` node[midway, above, font=\\tiny] {${esc(e.label)}}` : ''
    return `  \\draw[${arrow}] (${e.from}) --${labelPart} (${e.to});`
  })

  return [...header, ...nodeLines, ...edgeLines, '\\end{tikzpicture}'].join('\n')
}

/**
 * Network diagram — same as flowchart but edges default to bidirectional.
 */
export function generateNetwork(nodes: FlowNode[], edges: FlowEdge[]): string {
  const bidirEdges = edges.map((e) => ({ ...e, bidirectional: true }))
  return generateFlowchart(nodes, bidirEdges)
}
