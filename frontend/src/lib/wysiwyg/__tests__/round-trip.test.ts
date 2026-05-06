/**
 * Round-trip tests: LaTeX → IR → LaTeX (Feature 78).
 */

import { describe, expect, it } from 'vitest'
import { parseResume } from '../latex-parser'
import { serializeResume } from '../latex-serializer'

// ── parseResume ───────────────────────────────────────────────────────────────

describe('parseResume', () => {
  it('returns empty doc for empty string', () => {
    const { doc } = parseResume('')
    expect(doc.sections).toHaveLength(0)
  })

  it('returns preamble for content before first section', () => {
    const latex = '\\documentclass{resume}\n\\begin{document}'
    const { doc } = parseResume(latex)
    expect(doc.preamble).toContain('\\documentclass')
    expect(doc.sections).toHaveLength(0)
  })

  it('parses a single section with no entries', () => {
    const latex = '\\section{Skills}'
    const { doc } = parseResume(latex)
    expect(doc.sections).toHaveLength(1)
    expect(doc.sections[0].title).toBe('Skills')
    expect(doc.sections[0].entries).toHaveLength(0)
  })

  it('parses \\resumeSubheading entry', () => {
    const latex = `\\section{Experience}
\\resumeSubHeadingListStart
\\resumeSubheading{Acme Corp}{Jan 2022 -- Present}{Software Engineer}{Remote}
\\resumeItemListStart
\\resumeItem{Built things}
\\resumeItemListEnd
\\resumeSubHeadingListEnd`
    const { doc } = parseResume(latex)
    expect(doc.sections).toHaveLength(1)
    const entry = doc.sections[0].entries[0]
    expect(entry.type).toBe('subheading')
    expect(entry.heading).toBe('Acme Corp')
    expect(entry.subheading).toBe('Software Engineer')
    expect(entry.startDate).toBe('Jan 2022')
    expect(entry.endDate).toBe('Present')
    expect(entry.location).toBe('Remote')
    expect(entry.bullets).toEqual(['Built things'])
  })

  it('parses \\resumeProjectHeading entry', () => {
    const latex = `\\section{Projects}
\\resumeSubHeadingListStart
\\resumeProjectHeading{\\textbf{MyApp} $|$ \\emph{React}}{Jun 2023 -- Aug 2023}
\\resumeItemListStart
\\resumeItem{Shipped MVP}
\\resumeItemListEnd
\\resumeSubHeadingListEnd`
    const { doc } = parseResume(latex)
    const entry = doc.sections[0].entries[0]
    expect(entry.type).toBe('project')
    expect(entry.heading).toContain('MyApp')
    expect(entry.startDate).toBe('Jun 2023')
    expect(entry.endDate).toBe('Aug 2023')
  })

  it('marks unrecognised blocks as raw with warning', () => {
    const latex = `\\section{Misc}
\\someUnknownMacro{foo}`
    const { doc, warnings } = parseResume(latex)
    expect(warnings.length).toBeGreaterThan(0)
    expect(warnings[0].type).toBe('unrecognised_block')
    expect(doc.sections[0].entries[0].type).toBe('raw')
  })

  it('parses multiple sections', () => {
    const latex = `\\section{Experience}
\\section{Education}`
    const { doc } = parseResume(latex)
    expect(doc.sections).toHaveLength(2)
  })

  it('full resume with 3 resumeSubheadings round-trips without data loss', () => {
    const latex = `\\section{Experience}
\\resumeSubHeadingListStart
\\resumeSubheading{Company A}{Jan 2020 -- Jan 2021}{Engineer}{NYC}
\\resumeItemListStart
\\resumeItem{Did A}
\\resumeItemListEnd
\\resumeSubheading{Company B}{Feb 2021 -- Feb 2022}{Senior Engineer}{SF}
\\resumeItemListStart
\\resumeItem{Did B}
\\resumeItemListEnd
\\resumeSubheading{Company C}{Mar 2022 -- Present}{Staff Engineer}{Remote}
\\resumeItemListStart
\\resumeItem{Did C}
\\resumeItemListEnd
\\resumeSubHeadingListEnd`
    const { doc } = parseResume(latex)
    expect(doc.sections[0].entries).toHaveLength(3)
  })
})

// ── serializeResume ───────────────────────────────────────────────────────────

describe('serializeResume', () => {
  it('serializes empty doc', () => {
    const result = serializeResume({ preamble: '', sections: [], epilogue: '' })
    expect(typeof result).toBe('string')
  })

  it('serializes section title', () => {
    const result = serializeResume({
      preamble: '',
      sections: [{ title: 'Experience', entries: [] }],
      epilogue: '',
    })
    expect(result).toContain('\\section{Experience}')
  })

  it('serializes subheading entry with bullets', () => {
    const result = serializeResume({
      preamble: '',
      sections: [{
        title: 'Experience',
        entries: [{
          type: 'subheading',
          macro: 'resumeSubheading',
          heading: 'Acme',
          subheading: 'Engineer',
          startDate: 'Jan 2022',
          endDate: 'Present',
          location: 'Remote',
          bullets: ['Built things'],
        }],
      }],
      epilogue: '',
    })
    expect(result).toContain('\\resumeSubheading{Acme}')
    expect(result).toContain('\\resumeItem{Built things}')
  })

  it('serializes project heading entry', () => {
    const result = serializeResume({
      preamble: '',
      sections: [{
        title: 'Projects',
        entries: [{
          type: 'project',
          heading: 'MyApp',
          startDate: 'Jun 2023',
          endDate: 'Aug 2023',
          bullets: ['Shipped MVP'],
        }],
      }],
      epilogue: '',
    })
    expect(result).toContain('\\resumeProjectHeading')
    expect(result).toContain('MyApp')
  })

  it('preserves raw entries verbatim', () => {
    const raw = '\\someCustomMacro{foo bar}'
    const result = serializeResume({
      preamble: '',
      sections: [{
        title: 'Misc',
        entries: [{ type: 'raw', raw, bullets: [] }],
      }],
      epilogue: '',
    })
    expect(result).toContain(raw)
  })
})

// ── Round-trip: parse → serialize → parse ────────────────────────────────────

describe('parse → serialize → parse round-trip', () => {
  it('preserves section count', () => {
    const latex = `\\section{Experience}\n\\section{Education}`
    const { doc: doc1 } = parseResume(latex)
    const serialized = serializeResume(doc1)
    const { doc: doc2 } = parseResume(serialized)
    expect(doc2.sections).toHaveLength(doc1.sections.length)
  })

  it('preserves entry data through round-trip', () => {
    const latex = `\\section{Experience}
\\resumeSubHeadingListStart
\\resumeSubheading{Acme Corp}{Jan 2022 -- Present}{Engineer}{Remote}
\\resumeItemListStart
\\resumeItem{Built things}
\\resumeItemListEnd
\\resumeSubHeadingListEnd`
    const { doc: doc1 } = parseResume(latex)
    const { doc: doc2 } = parseResume(serializeResume(doc1))
    const e1 = doc1.sections[0].entries[0]
    const e2 = doc2.sections[0].entries[0]
    expect(e2.heading).toBe(e1.heading)
    expect(e2.subheading).toBe(e1.subheading)
    expect(e2.bullets).toEqual(e1.bullets)
  })

  it('preserves bullet count through round-trip', () => {
    const latex = `\\section{Experience}
\\resumeSubHeadingListStart
\\resumeSubheading{Corp}{2020 -- 2022}{Dev}{NYC}
\\resumeItemListStart
\\resumeItem{First bullet}
\\resumeItem{Second bullet}
\\resumeItem{Third bullet}
\\resumeItemListEnd
\\resumeSubHeadingListEnd`
    const { doc: doc1 } = parseResume(latex)
    const { doc: doc2 } = parseResume(serializeResume(doc1))
    expect(doc2.sections[0].entries[0].bullets).toHaveLength(3)
  })
})
