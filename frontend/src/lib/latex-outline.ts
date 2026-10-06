export interface LatexOutlineItem {
  command: 'part' | 'chapter' | 'section' | 'subsection' | 'subsubsection' | 'paragraph' | 'subparagraph'
  level: number
  label: string
  line: number
}

const LEVELS: Record<LatexOutlineItem['command'], number> = {
  part: 0,
  chapter: 1,
  section: 2,
  subsection: 3,
  subsubsection: 4,
  paragraph: 5,
  subparagraph: 6,
}

function spacesPreservingLines(value: string): string {
  return value.replace(/[^\n]/g, ' ')
}

function maskLiteralEnvironments(source: string): string {
  return source.replace(
    /\\begin\{(verbatim\*?|Verbatim|lstlisting|minted)\}[\s\S]*?\\end\{\1\}/g,
    spacesPreservingLines,
  )
}

export function stripLatexCommentsPreservingOffsets(source: string): string {
  return source
    .split('\n')
    .map((line) => {
      for (let index = 0; index < line.length; index += 1) {
        if (line[index] !== '%') continue
        let slashes = 0
        for (let cursor = index - 1; cursor >= 0 && line[cursor] === '\\'; cursor -= 1) {
          slashes += 1
        }
        if (slashes % 2 === 0) {
          return line.slice(0, index) + ' '.repeat(line.length - index)
        }
      }
      return line
    })
    .join('\n')
}

function skipWhitespace(source: string, start: number): number {
  let cursor = start
  while (/\s/.test(source[cursor] ?? '')) cursor += 1
  return cursor
}

function closingDelimiter(
  source: string,
  start: number,
  open: '[' | '{',
  close: ']' | '}',
): number | null {
  if (source[start] !== open) return null
  let depth = 1
  for (let cursor = start + 1; cursor < source.length; cursor += 1) {
    let slashes = 0
    for (let previous = cursor - 1; previous >= 0 && source[previous] === '\\'; previous -= 1) {
      slashes += 1
    }
    if (slashes % 2 === 1) continue
    if (source[cursor] === open) depth += 1
    if (source[cursor] === close) depth -= 1
    if (depth === 0) return cursor
  }
  return null
}

function readableTitle(raw: string): string {
  let title = raw.replace(/\s+/g, ' ').trim()
  let previous = ''
  while (title !== previous) {
    previous = title
    title = title.replace(
      /\\(?:textbf|textit|texttt|textsc|textrm|textsf|emph|MakeUppercase)\*?\s*\{([^{}]*)\}/g,
      '$1',
    )
  }
  return title || 'Untitled section'
}

export function buildLatexOutline(source: string): LatexOutlineItem[] {
  const searchable = stripLatexCommentsPreservingOffsets(maskLiteralEnvironments(source))
  const command = /\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?/g
  const items: LatexOutlineItem[] = []
  let match: RegExpExecArray | null

  while ((match = command.exec(searchable)) !== null) {
    let cursor = skipWhitespace(searchable, command.lastIndex)
    if (searchable[cursor] === '[') {
      const optionalEnd = closingDelimiter(searchable, cursor, '[', ']')
      if (optionalEnd === null) continue
      cursor = skipWhitespace(searchable, optionalEnd + 1)
    }
    if (searchable[cursor] !== '{') continue
    const titleEnd = closingDelimiter(searchable, cursor, '{', '}')
    if (titleEnd === null) continue
    const sectionCommand = match[1] as LatexOutlineItem['command']
    items.push({
      command: sectionCommand,
      level: LEVELS[sectionCommand],
      label: readableTitle(searchable.slice(cursor + 1, titleEnd)),
      line: searchable.slice(0, match.index).split('\n').length,
    })
    command.lastIndex = titleEnd + 1
  }
  return items
}
