/**
 * Turn selected imported GitHub projects into an insertable LaTeX snippet
 * (External-Sources-to-Resume, F1). Pure + React-free so it is unit tested and
 * reused by the import modal.
 *
 * The output is a template-agnostic block (bold title + optional repo link,
 * tech line, and an itemize of the user-selected bullets) guarded by a comment
 * so the user can see where it came from and move/edit it.
 */

import type { ProjectEvidence } from './api-client'

/** One project the user chose to insert, with the subset of bullets they kept. */
export interface ProjectSelection {
  project: ProjectEvidence
  bullets: string[]
}

const _LATEX_ESCAPES: Record<string, string> = {
  '\\': '\\textbackslash{}',
  '&': '\\&',
  '%': '\\%',
  $: '\\$',
  '#': '\\#',
  _: '\\_',
  '{': '\\{',
  '}': '\\}',
  '~': '\\textasciitilde{}',
  '^': '\\textasciicircum{}',
}

/**
 * Escape the LaTeX special characters that appear in free text. Single-pass so
 * the braces introduced by \textbackslash{} etc. are not themselves re-escaped.
 */
export function escapeLatex(text: string): string {
  return text.replace(/[\\&%$#_{}~^]/g, (c) => _LATEX_ESCAPES[c])
}

function projectBlock({ project, bullets }: ProjectSelection): string {
  const title = escapeLatex(project.title || 'Project')
  const lines: string[] = []

  const link =
    project.url && /^https?:\/\//i.test(project.url)
      ? ` \\href{${project.url}}{\\texttt{repo}}`
      : ''
  lines.push(`\\textbf{${title}}${link}`)

  const tech = (project.tech || []).filter(Boolean)
  if (tech.length > 0) {
    lines.push(`\\textit{${escapeLatex(tech.join(', '))}}`)
  }

  const kept = bullets.filter((b) => b && b.trim())
  if (kept.length > 0) {
    lines.push('\\begin{itemize}')
    for (const b of kept) lines.push(`  \\item ${escapeLatex(b.trim())}`)
    lines.push('\\end{itemize}')
  } else if (project.description) {
    lines.push(escapeLatex(project.description.trim()))
  }

  return lines.join('\n')
}

/**
 * Render the chosen projects (each with its kept bullets) into one LaTeX block.
 * Returns '' when nothing is selected so the caller can no-op.
 */
export function projectsToLatex(selections: ProjectSelection[]): string {
  const usable = selections.filter((s) => s.project && (s.bullets.length > 0 || s.project.description))
  if (usable.length === 0) return ''

  const blocks = usable.map(projectBlock).join('\n\n\\smallskip\n\n')
  return `% Projects imported from GitHub — edit freely\n${blocks}\n`
}
