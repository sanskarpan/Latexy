/** A conservative visual view. Edits patch original spans; never rebuild a document. */
export interface VisualField {
  id: string
  label: string
  value: string
  start: number
  end: number
  kind: 'heading' | 'text' | 'bullet'
  section: string
  sectionId: string
}

export interface VisualProjection {
  fields: VisualField[]
  unsupportedBlocks: number
}

const ESCAPES: Record<string, string> = { '%': '%', '&': '&', '#': '#', '_': '_', '$': '$', '{': '{', '}': '}' }
const LITERAL_COMMANDS: Record<string, string> = { textbackslash: '\\', textasciitilde: '~', textasciicircum: '^', mbox: '' }
const SAFE_TEXT_TOKEN = /\\(?:(textbackslash|textasciitilde|textasciicircum|mbox)\{\}|([%&#_$ {}]))/g
const SUPPORTED_ENVIRONMENTS = new Set(['document', 'center', 'itemize', 'enumerate'])

interface DocumentLine {
  /** Line content without its CRLF delimiter; offsets always refer to source. */
  text: string
  start: number
  end: number
  visible: boolean
}

interface ScannedDocument {
  lines: DocumentLine[]
  end: number | null
  unsupportedBlocks: number
}

function plain(value: string): string | null {
  if (/[\\{}$^~]/.test(value.replace(SAFE_TEXT_TOKEN, ''))) return null
  const decoded = value.replace(SAFE_TEXT_TOKEN, (_, command: string | undefined, char: string) => command ? LITERAL_COMMANDS[command] : ESCAPES[char] ?? char)
  // Normalize only the displayed value. Source offsets and the backing document
  // continue to use their original LF or CRLF representation.
  return decoded.replace(/\r\n/g, '\n')
}

function escapeText(value: string): string {
  if (value === '') return '\\mbox{}'
  return value.replace(/[\\%&#_$ {}^~]/g, (char) => {
    if (char === ' ') return char
    if (char === '\\') return '\\textbackslash{}'
    if (char === '~') return '\\textasciitilde{}'
    if (char === '^') return '\\textasciicircum{}'
    return `\\${char}`
  })
}

function braceArgs(line: string, from: number): { start: number; end: number }[] {
  const args: { start: number; end: number }[] = []
  let position = from
  while (position < line.length) {
    while (/\s/.test(line[position] ?? '') && position < line.length) position++
    if (line[position] !== '{') break
    const start = ++position
    let depth = 1
    while (position < line.length && depth) {
      if (line[position] === '\\') { position += 2; continue }
      if (line[position] === '{') depth++
      if (line[position] === '}') depth--
      position++
    }
    if (depth) break
    args.push({ start, end: position - 1 })
  }
  return args
}

function commentFree(line: string): string {
  return line.replace(/(?<!\\)%.*$/, '')
}

function unsupportedEnvironmentStart(line: string): string | null {
  const code = commentFree(line)
  const begins = /\\begin\{([^}]+)\}/g
  for (const match of code.matchAll(begins)) {
    if (!SUPPORTED_ENVIRONMENTS.has(match[1])) return match[1]
  }
  return null
}

/**
 * Find the real document body while treating unsupported environments as
 * opaque. In particular, commands that merely appear inside verbatim/listing
 * content cannot terminate the document or create visual fields.
 */
function scanDocument(source: string): ScannedDocument {
  const lines: DocumentLine[] = []
  const rawLines = source.split('\n')
  let offset = 0
  let inDocument = false
  let ignoredEnvironment: string | null = null
  let ignoredDepth = 0
  let unsupportedBlocks = 0
  let end: number | null = null

  for (const rawLine of rawLines) {
    const text = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    const trimmed = text.trim()
    const line: DocumentLine = { text, start: offset, end: offset + text.length, visible: false }

    if (!inDocument) {
      if (/^\\begin\{document\}/.test(trimmed)) inDocument = true
      offset += rawLine.length + 1
      continue
    }

    if (ignoredEnvironment) {
      // Only the matching end marker can leave an opaque block. This keeps a
      // literal \end{document} or nested itemize example inert inside it.
      const escapedName = ignoredEnvironment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const delimiter = new RegExp(`\\\\(begin|end)\\{${escapedName}\\}`, 'g')
      for (const match of text.matchAll(delimiter)) {
        if (match[1] === 'begin') ignoredDepth++
        else if (--ignoredDepth === 0) { ignoredEnvironment = null; break }
      }
      lines.push(line)
      offset += rawLine.length + 1
      continue
    }

    if (/^\\end\{document\}/.test(trimmed)) {
      end = offset + text.length - trimmed.length
      break
    }

    const unsupported = unsupportedEnvironmentStart(text)
    if (unsupported) {
      unsupportedBlocks++
      ignoredEnvironment = unsupported
      ignoredDepth = 0
      // Count the opening marker below exactly once, including nested starts
      // on this line, so a complete one-line opaque block can close.
      // Handle a complete unsupported environment written on one line too.
      const escapedName = unsupported.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const delimiter = new RegExp(`\\\\(begin|end)\\{${escapedName}\\}`, 'g')
      for (const match of text.matchAll(delimiter)) {
        if (match[1] === 'begin') ignoredDepth++
        else if (--ignoredDepth === 0) { ignoredEnvironment = null; break }
      }
      lines.push(line)
      offset += rawLine.length + 1
      continue
    }

    line.visible = true
    lines.push(line)
    offset += rawLine.length + 1
  }

  return { lines, end, unsupportedBlocks }
}

function sectionCommand(line: string): RegExpMatchArray | null {
  return line.trim().match(/^\\(?:section\*?|cvsection)\{/)
}

function braceDepth(line: string): number {
  let depth = 0
  for (let index = 0; index < line.length; index++) {
    if (line[index] === '\\') { index++; continue }
    if (line[index] === '{') depth++
    else if (line[index] === '}') depth--
  }
  return depth
}

function sectionBodyEnd(document: ScannedDocument, sourceLength: number, heading: VisualField): number {
  const nextHeading = document.lines.find((line) => line.visible && line.start > heading.start && sectionCommand(line.text))
  return nextHeading?.start ?? document.end ?? sourceLength
}

export function projectVisualResume(source: string): VisualProjection {
  const document = scanDocument(source)
  const fields: VisualField[] = []
  let section = 'Personal details'
  let sectionId = 'section-0'
  let sectionNumber = 0
  let previousPlain = false

  function add(line: string, lineOffset: number, start: number, end: number, label: string, kind: VisualField['kind'] = 'text'): boolean {
    const comment = line.slice(start, end).search(/(?<!\\)%/)
    if (comment >= 0) {
      end = start + comment
      while (end > start && (line[end - 1] === ' ' || line[end - 1] === '\t')) end--
    }
    const raw = line.slice(start, end)
    // Preserve supported formatting wrappers by editing their inner text only.
    const wrapper = raw.match(/^\\(?:textbf|textit|emph|underline)\{/)
    if (wrapper) {
      const args = braceArgs(raw, wrapper[0].length - 1)
      if (args.length === 1 && args[0].end === raw.length - 1) {
        return add(line, lineOffset, start + args[0].start, start + args[0].end, label, kind)
      }
    }
    const value = plain(raw)
    if (value === null) return false
    fields.push({ id: `${sectionId}-${fields.filter((field) => field.sectionId === sectionId).length}`, label, value, start: lineOffset + start, end: lineOffset + end, kind, section, sectionId })
    return true
  }

  const macroArgumentCounts: Record<string, number> = { resumeSubheading: 4, resumeProjectHeading: 2, resumeItem: 1, cventry: 6, cvevent: 4 }
  const macroLabels: Record<string, string[]> = {
    resumeSubheading: ['Role or qualification', 'Dates', 'Organization', 'Location'],
    resumeProjectHeading: ['Project', 'Dates'], resumeItem: ['Achievement'],
    cventry: ['Dates', 'Role or qualification', 'Organization', 'Location', '', 'Description'],
    cvevent: ['Role or qualification', 'Organization', 'Dates', 'Location'],
  }

  for (let index = 0; index < document.lines.length; index++) {
    const entry = document.lines[index]
    if (!entry.visible) { previousPlain = false; continue }

    let line = entry.text
    let lineOffset = entry.start
    const multiLineMacro = line.trim().match(/^\\(resumeSubheading|resumeProjectHeading|resumeItem|cventry|cvevent)\b/)
    if (multiLineMacro) {
      const from = line.indexOf(multiLineMacro[0]) + multiLineMacro[0].length
      let args = braceArgs(line, from)
      let nextIndex = index + 1
      while (args.length < macroArgumentCounts[multiLineMacro[1]] && nextIndex < document.lines.length) {
        const next = document.lines[nextIndex]
        if (!next.visible || sectionCommand(next.text) || /^\s*\\[A-Za-z@]+/.test(next.text)) break
        line = source.slice(entry.start, next.end)
        args = braceArgs(line, from)
        nextIndex++
      }
      index = nextIndex - 1
    } else if (line.includes('\\textbf{') && braceDepth(line.slice(line.indexOf('\\textbf{') + 7)) > 0) {
      let nextIndex = index + 1
      while (braceDepth(line.slice(line.indexOf('\\textbf{') + 7)) > 0 && nextIndex < document.lines.length) {
        const next = document.lines[nextIndex]
        if (!next.visible || sectionCommand(next.text) || /^\s*\\[A-Za-z@]+/.test(next.text)) break
        line = source.slice(entry.start, next.end)
        nextIndex++
      }
      index = nextIndex - 1
    }

    const trimmed = line.trim()
    const indent = line.length - line.trimStart().length
    if (!trimmed || trimmed.startsWith('%')) {
      // Blank lines are part of a multiline editable value. A real command or
      // opaque block below breaks the merge when it is encountered.
      if (trimmed.startsWith('%')) previousPlain = false
      else if (/^[ \t]+$/.test(line) && !fields.some((field) => field.sectionId === sectionId && field.kind !== 'heading')) {
        fields.push({ id: `${sectionId}-${fields.filter((field) => field.sectionId === sectionId).length}`, label: section === 'Personal details' ? 'Contact or headline' : 'Description', value: line, start: entry.start, end: entry.end, kind: 'text', section, sectionId })
        previousPlain = true
      } else if (line === '' && !fields.some((field) => field.sectionId === sectionId && field.kind !== 'heading')) {
        fields.push({ id: `${sectionId}-${fields.filter((field) => field.sectionId === sectionId).length}`, label: section === 'Personal details' ? 'Contact or headline' : 'Description', value: '\n', start: entry.start, end: entry.end, kind: 'text', section, sectionId })
        previousPlain = true
      } else if (line === '' && previousPlain) {
        const last = fields[fields.length - 1]
        if (last && last.sectionId === sectionId && last.kind !== 'heading') {
          const value = plain(source.slice(last.start, entry.end))
          if (value !== null) { last.end = entry.end; last.value = value }
        }
      }
      continue
    }

    const sectionMatch = sectionCommand(line)
    if (sectionMatch) {
      const args = braceArgs(line, indent + sectionMatch[0].length - 1)
      const title = args[0] ? plain(line.slice(args[0].start, args[0].end)) : null
      section = title || 'Untitled section'
      // IDs are positional, not title-derived, so repeated titles remain
      // separate visual groups.
      sectionId = `section-${++sectionNumber}`
      if (args[0]) add(line, entry.start, args[0].start, args[0].end, 'Section title', 'heading')
      previousPlain = false
    } else if (/^\\(?:begin|end)\{(?:center|itemize|enumerate)\}|^\\(?:vspace|hspace|resume\w*(?:Start|End))\b/.test(trimmed)) {
      previousPlain = false
    } else {
      const macro = trimmed.match(/^\\(resumeSubheading|resumeProjectHeading|resumeItem|cventry|cvevent)\b/)
      if (macro) {
        const args = braceArgs(line, indent + macro[0].length)
        args.forEach((arg, argIndex) => {
          const label = macroLabels[macro[1]][argIndex]
          if (label && !add(line, entry.start, arg.start, arg.end, label, macro[1] === 'resumeItem' ? 'bullet' : 'text')) document.unsupportedBlocks++
        })
        previousPlain = false
      } else if (/^\\item(?:\s|$)/.test(trimmed)) {
        let start = line.indexOf('\\item') + '\\item'.length
        if (line[start] === ' ' || line[start] === '\t') start++
        if (!add(line, entry.start, start, line.length, 'Achievement', 'bullet')) document.unsupportedBlocks++
        previousPlain = false
      } else if (/\\textbf\{/.test(line) && !/\\(?:href|newcommand|renewcommand)/.test(line)) {
        const start = line.indexOf('\\textbf{') + 7
        const args = braceArgs(line, start)
        if (args[0] && !add(line, entry.start, args[0].start, args[0].end, section === 'Personal details' ? 'Name' : 'Role or qualification')) document.unsupportedBlocks++
        const date = line.indexOf('\\hfill')
        if (date >= 0) add(line, entry.start, date + 6, line.length, 'Dates')
        previousPlain = false
      } else {
        const lineBreak = /\\\\[ \t]*$/.exec(line)
        const end = lineBreak ? lineBreak.index : line.length
        const content = plain(line.slice(indent, end).replace(/(?<!\\)%.*$/, ''))
        if (content !== null && (content !== '' || end > indent || trimmed === '\\mbox{}')) {
          const last = fields[fields.length - 1]
          const nextStart = entry.start + indent
          const gap = last ? source.slice(last.end, nextStart) : ''
          if (previousPlain && last && last.sectionId === sectionId && /^\s*$/.test(gap)) {
            const merged = plain(source.slice(last.start, entry.start + end))
            if (merged !== null) {
              last.end = entry.start + end
              last.value = merged
            }
          } else add(line, lineOffset, indent, end, section === 'Personal details' ? 'Contact or headline' : 'Description')
          previousPlain = true
        } else { document.unsupportedBlocks++; previousPlain = false }
      }
    }
  }

  return { fields, unsupportedBlocks: document.unsupportedBlocks }
}

export function updateVisualField(source: string, field: VisualField, value: string): string {
  // A stale field must never replace a different part of a changed document.
  const current = projectVisualResume(source).fields.find((candidate) => candidate.id === field.id)
  if (!current || current.start !== field.start || current.end !== field.end || current.value !== field.value) return source
  return source.slice(0, field.start) + escapeText(value) + source.slice(field.end)
}

/** Safe prose for visual-mode proposal review; unsupported markup is never emitted. */
export function visualResumeText(source: string): string {
  return projectVisualResume(source).fields.map((field) => `${field.label}: ${field.value}`).join('\n')
}

function documentEnd(source: string): number | null {
  return scanDocument(source).end
}

function sourceNewline(source: string): string {
  return source.includes('\r\n') ? '\r\n' : '\n'
}

export function appendVisualSection(source: string): string {
  const end = documentEnd(source)
  if (end === null) return source
  const newline = sourceNewline(source)
  const titles = new Set(projectVisualResume(source).fields.filter((field) => field.kind === 'heading').map((field) => field.value))
  let title = 'Additional experience'
  for (let index = 2; titles.has(title); index++) title = `Additional experience ${index}`
  return source.slice(0, end) + `${newline}\\section*{${title}}${newline}Describe an achievement, project, or qualification here.${newline}${newline}` + source.slice(end)
}

/** Inserts supported content at a section boundary without rewriting its layout. */
export function addVisualSectionContent(source: string, heading: VisualField): { source: string; kind: 'achievement' | 'paragraph' } {
  const fallback = { source, kind: 'paragraph' as const }
  const current = projectVisualResume(source).fields.find((field) => field.id === heading.id)
  if (!current || current.kind !== 'heading' || current.start !== heading.start || current.value !== heading.value) return fallback
  const newline = source.indexOf('\n', heading.end)
  const document = scanDocument(source)
  if (newline < 0 || document.end === null) return fallback
  const bodyStart = newline + 1
  const bodyEnd = sectionBodyEnd(document, source.length, heading)
  const visibleBody = document.lines.filter((line) => line.visible && line.start >= bodyStart && line.start < bodyEnd)
  const hasOpaqueBlock = document.lines.some((line) => !line.visible && line.start >= bodyStart && line.start < bodyEnd)
  const hasEditableContent = visibleBody.some((line) => {
    const text = line.text.trim()
    return text !== '' && !/^\\(?:begin|end)\{(?:center|itemize|enumerate)\}/.test(text) && !/^\\(?:vspace|hspace|resume\w*(?:Start|End))\b/.test(text)
  })
  if (hasOpaqueBlock && !hasEditableContent) return fallback

  const listStart = visibleBody.findIndex((line) => /^\s*\\begin\{itemize\}/.test(line.text))
  const listEnd = listStart < 0 ? -1 : visibleBody.findIndex((line, index) => index > listStart && /^\s*\\end\{itemize\}/.test(line.text))
  if (listStart >= 0 && listEnd >= 0) {
    const insertion = visibleBody[listEnd].start
    return { source: source.slice(0, insertion) + `\\item Describe your achievement here.${sourceNewline(source)}` + source.slice(insertion), kind: 'achievement' }
  }

  // Do not inject prose into an open visible environment or grouped custom layout.
  // Opaque blocks are absent from this check and remain byte-for-byte untouched.
  const safeBody = visibleBody.map((line) => commentFree(line.text)).join('\n').replace(/\\[{}]/g, '')
  let depth = 0
  for (const char of safeBody) { if (char === '{') depth++; if (char === '}') depth-- }
  const begins = [...safeBody.matchAll(/\\begin\{/g)].length
  const ends = [...safeBody.matchAll(/\\end\{/g)].length
  if (depth !== 0 || begins !== ends) return fallback
  const newlineStyle = sourceNewline(source)
  return { source: source.slice(0, bodyEnd) + `${newlineStyle}Describe your experience here.${newlineStyle}${newlineStyle}` + source.slice(bodyEnd), kind: 'paragraph' }
}
