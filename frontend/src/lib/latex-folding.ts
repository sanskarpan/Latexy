import { buildLatexOutline, stripLatexCommentsPreservingOffsets } from '@/lib/latex-outline'

export interface LatexFoldingRange {
  start: number
  end: number
}

const LITERAL_ENVIRONMENTS = new Set(['verbatim', 'verbatim*', 'Verbatim', 'lstlisting', 'minted'])

export function buildLatexFoldingRanges(source: string): LatexFoldingRange[] {
  const searchable = stripLatexCommentsPreservingOffsets(source)
  const ranges: LatexFoldingRange[] = []
  const stack: Array<{ environment: string; line: number; literal: boolean }> = []
  const token = /\\(begin|end)\s*\{([^}\s]+)\}/g
  let match: RegExpExecArray | null

  while ((match = token.exec(searchable)) !== null) {
    const type = match[1]
    const environment = match[2]
    const line = searchable.slice(0, match.index).split('\n').length
    const top = stack[stack.length - 1]
    if (top?.literal && !(type === 'end' && environment === top.environment)) {
      continue
    }
    if (type === 'begin') {
      stack.push({ environment, line, literal: LITERAL_ENVIRONMENTS.has(environment) })
      continue
    }
    const opened = stack[stack.length - 1]
    if (!opened || opened.environment !== environment) continue
    stack.pop()
    if (line > opened.line) ranges.push({ start: opened.line, end: line })
  }

  const lines = source.split('\n').length
  const outline = buildLatexOutline(source)
  for (let index = 0; index < outline.length; index += 1) {
    const item = outline[index]
    let end = lines
    for (let next = index + 1; next < outline.length; next += 1) {
      if (outline[next].level <= item.level) {
        end = outline[next].line - 1
        break
      }
    }
    if (end > item.line) ranges.push({ start: item.line, end })
  }

  const unique = new Map(ranges.map((range) => [`${range.start}:${range.end}`, range]))
  return [...unique.values()].sort((left, right) => left.start - right.start || right.end - left.end)
}
