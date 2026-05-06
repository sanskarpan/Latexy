/**
 * IR → LaTeX serializer (Feature 78).
 *
 * Reconstructs a LaTeX resume source from a `ResumeDoc` IR.
 */

import type { Entry, ResumeDoc } from './document-model'

export function serializeResume(doc: ResumeDoc): string {
  const parts: string[] = []

  if (doc.preamble) parts.push(doc.preamble)

  for (const section of doc.sections) {
    parts.push(`\n\\section{${section.title}}`)

    const hasNonBullets = section.entries.some((e) => e.type !== 'bullets' && e.type !== 'raw')
    if (hasNonBullets) parts.push('\\resumeSubHeadingListStart')

    for (const entry of section.entries) {
      parts.push(serializeEntry(entry))
    }

    if (hasNonBullets) parts.push('\\resumeSubHeadingListEnd')
  }

  if (doc.epilogue) parts.push(doc.epilogue)

  return parts.join('\n')
}

function serializeEntry(entry: Entry): string {
  const lines: string[] = []

  switch (entry.type) {
    case 'subheading': {
      const macro = entry.macro ?? 'resumeSubheading'
      const dateRange = joinDates(entry.startDate, entry.endDate)
      lines.push(
        `\\${macro}{${entry.heading ?? ''}}{${dateRange}}{${entry.subheading ?? ''}}{${entry.location ?? ''}}`
      )
      if (entry.bullets.length > 0) {
        lines.push('\\resumeItemListStart')
        for (const b of entry.bullets) lines.push(`  \\resumeItem{${b}}`)
        lines.push('\\resumeItemListEnd')
      }
      break
    }

    case 'project': {
      const dateRange = joinDates(entry.startDate, entry.endDate)
      const headingLatex = entry.heading
        ? `\\textbf{${entry.heading}}`
        : ''
      lines.push(`\\resumeProjectHeading{${headingLatex}}{${dateRange}}`)
      if (entry.bullets.length > 0) {
        lines.push('\\resumeItemListStart')
        for (const b of entry.bullets) lines.push(`  \\resumeItem{${b}}`)
        lines.push('\\resumeItemListEnd')
      }
      break
    }

    case 'cventry': {
      const dateRange = joinDates(entry.startDate, entry.endDate)
      const desc = entry.bullets.length > 0 ? entry.bullets[0] : ''
      lines.push(
        `\\cventry{${dateRange}}{${entry.heading ?? ''}}{${entry.subheading ?? ''}}{${entry.location ?? ''}}{}{${desc}}`
      )
      break
    }

    case 'cvevent': {
      const dateRange = joinDates(entry.startDate, entry.endDate)
      lines.push(
        `\\cvevent{${entry.heading ?? ''}}{${entry.subheading ?? ''}}{${dateRange}}{${entry.location ?? ''}}`
      )
      if (entry.bullets.length > 0) {
        lines.push('\\begin{itemize}')
        for (const b of entry.bullets) lines.push(`  \\item ${b}`)
        lines.push('\\end{itemize}')
      }
      break
    }

    case 'bullets': {
      lines.push('\\resumeItemListStart')
      for (const b of entry.bullets) lines.push(`  \\resumeItem{${b}}`)
      lines.push('\\resumeItemListEnd')
      break
    }

    case 'raw':
    default:
      if (entry.raw) lines.push(entry.raw)
      break
  }

  return lines.join('\n')
}

function joinDates(start?: string, end?: string): string {
  if (start && end) return `${start} -- ${end}`
  return start ?? end ?? ''
}
