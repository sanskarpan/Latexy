/**
 * LaTeX → IR parser (Feature 78).
 *
 * Parses a LaTeX resume source into a `ResumeDoc` intermediate representation.
 * Designed for the common jake-gutenberg / AltaCV template conventions.
 */

import type { Entry, EntryType, ParseResult, ParseWarning, ResumeDoc, Section } from './document-model'

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Extract up to `n` balanced-brace arguments starting at `pos` in `src`. */
function extractBraceArgs(src: string, pos: number, n: number): string[] {
  const args: string[] = []
  let i = pos
  while (args.length < n && i < src.length) {
    // skip whitespace between args
    while (i < src.length && /\s/.test(src[i])) i++
    if (src[i] !== '{') break
    let depth = 0
    let start = i
    let j = i
    while (j < src.length) {
      if (src[j] === '{') depth++
      else if (src[j] === '}') {
        depth--
        if (depth === 0) { j++; break }
      }
      j++
    }
    args.push(src.slice(start + 1, j - 1).trim())
    i = j
  }
  return args
}

/** True if the line is a \resumeXxx(Start|End) wrapper — should be skipped. */
const SKIP_RE = /^\\resume\w*(?:Start|End)\b/

/** True if the line starts a new entry block. */
const ENTRY_START_RE = /^\\(?:resumeSubheading|resumeProjectHeading|cventry|cvevent)\b/

/** True if this is a section heading. */
const SECTION_RE = /^\\section\{([^}]*)\}/

/** Parse a single \resumeItem bullet. */
const ITEM_RE = /^\\resumeItem\{([\s\S]*)\}/

// ── Core parser ───────────────────────────────────────────────────────────────

export function parseResume(latex: string): ParseResult {
  const warnings: ParseWarning[] = []
  const sections: Section[] = []
  let preamble = ''
  let epilogue = ''

  const lines = latex.split('\n')
  let inBody = false      // have we seen the first \section?
  let preambleLines: string[] = []
  let epilogueLines: string[] = []
  let currentSection: Section | null = null
  let buffer: string[] = []  // lines accumulated for one entry block

  function flushBuffer() {
    if (buffer.length === 0) return
    const block = buffer.join('\n').trim()
    buffer = []
    if (!block) return
    if (!currentSection) return

    const entry = parseBlock(block, warnings)
    currentSection.entries.push(entry)
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    // Skip wrapper macros entirely
    if (SKIP_RE.test(trimmed)) continue

    // Section heading — flush current buffer, start new section
    const sectionMatch = trimmed.match(SECTION_RE)
    if (sectionMatch) {
      flushBuffer()
      inBody = true
      currentSection = { title: sectionMatch[1], entries: [] }
      sections.push(currentSection)
      continue
    }

    if (!inBody) {
      preambleLines.push(line)
      continue
    }

    // Blank line — flush (end of block)
    if (!trimmed) {
      flushBuffer()
      continue
    }

    // Entry-starting macro — flush previous block, start new
    if (ENTRY_START_RE.test(trimmed)) {
      flushBuffer()
    }

    buffer.push(line)
  }

  flushBuffer()

  // Separate preamble / epilogue
  preamble = preambleLines.join('\n')
  epilogue = epilogueLines.join('\n')

  const doc: ResumeDoc = { preamble, sections, epilogue }
  return { doc, warnings }
}

// ── Block parsers ─────────────────────────────────────────────────────────────

function parseBlock(block: string, warnings: ParseWarning[]): Entry {
  const firstLine = block.split('\n')[0].trim()

  if (/^\\resumeSubheading\b/.test(firstLine)) {
    return parseSubheading(block, 'resumeSubheading')
  }
  if (/^\\resumeProjectHeading\b/.test(firstLine)) {
    return parseProjectHeading(block)
  }
  if (/^\\cventry\b/.test(firstLine)) {
    return parseCventry(block)
  }
  if (/^\\cvevent\b/.test(firstLine)) {
    return parseCvevent(block)
  }
  if (/^\\begin\{itemize\}/.test(firstLine)) {
    return parseStandaloneItemize(block)
  }

  // Unrecognised — store as raw
  warnings.push({ type: 'unrecognised_block', message: 'Unrecognised block', raw: block })
  return { type: 'raw', raw: block, bullets: [] }
}

function extractBullets(block: string): string[] {
  const bullets: string[] = []
  const lines = block.split('\n')
  for (const line of lines) {
    const t = line.trim()
    const itemMatch = t.match(/^\\resumeItem\{([\s\S]*)\}$/) || t.match(/^\\item\s+(.*)/)
    if (itemMatch) bullets.push(itemMatch[1].trim())
  }
  return bullets
}

function parseSubheading(block: string, macro: string): Entry {
  // \resumeSubheading{Heading}{Date}{Subheading}{Location}
  const commandEnd = block.indexOf('\\resumeSubheading') + '\\resumeSubheading'.length
  const args = extractBraceArgs(block, commandEnd, 4)
  const [heading = '', dateRange = '', subheading = '', location = ''] = args
  const [startDate, endDate] = splitDateRange(dateRange)
  const bullets = extractBullets(block)
  return { macro, type: 'subheading', heading, subheading, startDate, endDate, location, bullets }
}

function parseProjectHeading(block: string): Entry {
  // \resumeProjectHeading{\textbf{Title} $|$ \emph{Tech}}{Date}
  const commandEnd = block.indexOf('\\resumeProjectHeading') + '\\resumeProjectHeading'.length
  const args = extractBraceArgs(block, commandEnd, 2)
  const [headingRaw = '', dateRange = ''] = args
  // strip latex formatting to get plain heading
  const heading = headingRaw
    .replace(/\\textbf\{([^}]*)\}/g, '$1')
    .replace(/\\emph\{([^}]*)\}/g, '$1')
    .replace(/\$\s*\|\s*\$/g, '|')
    .trim()
  const [startDate, endDate] = splitDateRange(dateRange)
  const bullets = extractBullets(block)
  return { macro: 'resumeProjectHeading', type: 'project', heading, startDate, endDate, bullets }
}

function parseCventry(block: string): Entry {
  // \cventry{dates}{title}{employer}{location}{}{description}
  const commandEnd = block.indexOf('\\cventry') + '\\cventry'.length
  const args = extractBraceArgs(block, commandEnd, 6)
  const [dateRange = '', heading = '', subheading = '', location = '', , desc = ''] = args
  const [startDate, endDate] = splitDateRange(dateRange)
  const bullets = desc ? [desc] : extractBullets(block)
  return { macro: 'cventry', type: 'cventry', heading, subheading, startDate, endDate, location, bullets }
}

function parseCvevent(block: string): Entry {
  // \cvevent{title}{employer}{date range}{location}
  const commandEnd = block.indexOf('\\cvevent') + '\\cvevent'.length
  const args = extractBraceArgs(block, commandEnd, 4)
  const [heading = '', subheading = '', dateRange = '', location = ''] = args
  const [startDate, endDate] = splitDateRange(dateRange)
  const bullets = extractBullets(block)
  return { macro: 'cvevent', type: 'cvevent', heading, subheading, startDate, endDate, location, bullets }
}

function parseStandaloneItemize(block: string): Entry {
  const bullets = extractBullets(block)
  return { type: 'bullets', bullets }
}

function splitDateRange(dateRange: string): [string, string] {
  // Common separators: " -- ", " - ", " to ", "–", "—"
  const sep = / -- | – | — | - | to /
  const parts = dateRange.split(sep)
  if (parts.length >= 2) return [parts[0].trim(), parts[parts.length - 1].trim()]
  return [dateRange.trim(), '']
}
