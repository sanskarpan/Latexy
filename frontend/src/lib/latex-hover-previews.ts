import { stripLatexCommentsPreservingOffsets } from '@/lib/latex-outline'

export type LatexHoverPreview =
  | { kind: 'math'; start: number; end: number; latex: string; displayMode: boolean }
  | { kind: 'graphic'; start: number; end: number; filename: string; options: string | null }
  | { kind: 'citation'; start: number; end: number; citations: CitationPreview[] }

export interface CitationPreview {
  key: string
  type?: string
  title?: string
  author?: string
  year?: string
}

/**
 * Wrap untrusted text in a Markdown inline code span without interpreting
 * backslashes or colliding with backtick runs in the value.
 */
export function markdownCodeSpan(value: string): string {
  // CommonMark cannot keep a blank paragraph inside an inline span. Normalize
  // line endings before wrapping so they cannot expose Markdown outside it.
  value = value.replace(/\r\n?|\n/g, ' ')
  let longestBacktickRun = 0
  let run = 0
  for (const char of value) {
    run = char === '`' ? run + 1 : 0
    longestBacktickRun = Math.max(longestBacktickRun, run)
  }
  const delimiterLength = Math.max(longestBacktickRun + 1, value.startsWith('`') || value.endsWith('`') ? 2 : 1)
  const delimiter = '`'.repeat(delimiterLength)
  const needsBoundaryPadding = !/^\s+$/.test(value) && (
    value.startsWith(' ') || value.endsWith(' ') || value.startsWith('`') || value.endsWith('`')
  )
  const body = needsBoundaryPadding ? ` ${value} ` : value
  return `${delimiter}${body}${delimiter}`
}

function blank(value: string): string {
  return value.replace(/[^\n]/g, ' ')
}

function searchableSource(source: string): string {
  return stripLatexCommentsPreservingOffsets(source.replace(
    /\\begin\{(verbatim\*?|Verbatim|lstlisting|minted)\}[\s\S]*?\\end\{\1\}/g,
    blank,
  ))
}

function unbrace(value: string): string {
  let result = value.trim()
  while (result.startsWith('{') && result.endsWith('}')) result = result.slice(1, -1).trim()
  return result.replace(/\s+/g, ' ')
}

export function parseBibTeXPreviews(bibliography: string): Map<string, CitationPreview> {
  const entries = new Map<string, CitationPreview>()
  const start = /@([A-Za-z]+)\s*([({])\s*([^,\s}]+)\s*,/g
  let match: RegExpExecArray | null
  while ((match = start.exec(bibliography)) !== null) {
    const close = match[2] === '{' ? '}' : ')'
    let depth = 1
    let quoted = false
    let escaped = false
    let cursor = start.lastIndex
    for (; cursor < bibliography.length; cursor += 1) {
      const char = bibliography[cursor]
      if (escaped) { escaped = false; continue }
      if (char === '\\') { escaped = true; continue }
      if (char === '"') quoted = !quoted
      if (quoted) continue
      if (char === match[2]) depth += 1
      if (char === close) depth -= 1
      if (depth === 0) break
    }
    const body = bibliography.slice(start.lastIndex, cursor)
    const fields: Record<string, string> = {}
    const field = /\b(title|author|year)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|"(?:[^"\\]|\\.)*"|[^,\n]+)/gi
    let fieldMatch: RegExpExecArray | null
    while ((fieldMatch = field.exec(body)) !== null) {
      fields[fieldMatch[1].toLowerCase()] = unbrace(fieldMatch[2].replace(/^"|"$/g, ''))
    }
    entries.set(match[3].trim(), {
      key: match[3].trim(),
      type: match[1].toLowerCase(),
      title: fields.title,
      author: fields.author,
      year: fields.year,
    })
    start.lastIndex = Math.max(start.lastIndex, cursor + 1)
  }
  return entries
}

function previewFromPattern(
  source: string,
  offset: number,
  expression: RegExp,
  make: (match: RegExpExecArray) => LatexHoverPreview,
): LatexHoverPreview | null {
  let match: RegExpExecArray | null
  while ((match = expression.exec(source)) !== null) {
    if (offset >= match.index && offset <= match.index + match[0].length) return make(match)
  }
  return null
}

export function buildLatexHoverPreview(
  source: string,
  bibliography: string,
  offset: number,
): LatexHoverPreview | null {
  const searchable = searchableSource(source)
  const mathPatterns: Array<{ expression: RegExp; group: number; displayMode: boolean }> = [
    { expression: /\$\$([\s\S]*?)\$\$/g, group: 1, displayMode: true },
    { expression: /\\\[([\s\S]*?)\\\]/g, group: 1, displayMode: true },
    { expression: /\\\(([\s\S]*?)\\\)/g, group: 1, displayMode: false },
    { expression: /\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}([\s\S]*?)\\end\{\1\}/g, group: 2, displayMode: true },
    { expression: /(^|[^\\$])\$([^$\n]+?)(?<!\\)\$/gm, group: 2, displayMode: false },
  ]
  for (const pattern of mathPatterns) {
    const preview = previewFromPattern(searchable, offset, pattern.expression, (match) => ({
      kind: 'math',
      start: match.index + (match[1] && pattern.group === 2 ? match[1].length : 0),
      end: match.index + match[0].length,
      latex: match[pattern.group].trim(),
      displayMode: pattern.displayMode,
    }))
    if (preview) return preview
  }

  const graphic = previewFromPattern(
    searchable,
    offset,
    /\\includegraphics\s*(?:\[([^\]]*)\])?\s*\{([^{}]+)\}/g,
    (match) => ({
      kind: 'graphic',
      start: match.index,
      end: match.index + match[0].length,
      filename: match[2].trim(),
      options: match[1]?.trim() || null,
    }),
  )
  if (graphic) return graphic

  const citation = previewFromPattern(
    searchable,
    offset,
    /\\(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|citeyearpar|nocite|parencite|textcite|autocite|footcite|smartcite)\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}/g,
    (match) => {
      const metadata = parseBibTeXPreviews(`${source}\n${bibliography}`)
      return {
        kind: 'citation',
        start: match.index,
        end: match.index + match[0].length,
        citations: match[1].split(',').map((rawKey) => {
          const key = rawKey.trim()
          return metadata.get(key) ?? { key }
        }).filter((item) => item.key),
      }
    },
  )
  return citation
}
