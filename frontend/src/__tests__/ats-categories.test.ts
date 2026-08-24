import { describe, it, expect } from 'vitest'
import {
  buildATSCategories,
  resolveFindingLine,
  ATS_CATEGORY_LABELS,
  type ATSCategoryInput,
} from '@/lib/ats-categories'

const LATEX = [
  '\\documentclass{article}',      // 1
  '\\begin{document}',             // 2
  '\\section{Experience}',         // 3
  'Senior Engineer, Acme',         // 4
  '2020',                          // 5  (bare date)
  'jane@example.com',              // 6  (email)
  '\\end{document}',               // 7
].join('\n')

describe('buildATSCategories', () => {
  it('always returns the five categories in a stable order', () => {
    const cats = buildATSCategories({})
    expect(cats.map((c) => c.key)).toEqual([
      'content',
      'format',
      'optimization',
      'best_practices',
      'application_ready',
    ])
    expect(cats.map((c) => c.label)).toEqual(Object.values(ATS_CATEGORY_LABELS))
  })

  it('a clean résumé leaves every category "good" with no findings', () => {
    const cats = buildATSCategories({ quick: { missingSections: [], keywordMatchPercent: 90 }, simulatorIssues: [] })
    expect(cats.every((c) => c.status === 'good' && c.findings.length === 0)).toBe(true)
  })

  it('maps a missing section into Content and Application Ready as a high-severity finding', () => {
    const cats = buildATSCategories({ quick: { missingSections: ['experience'] } })
    const content = cats.find((c) => c.key === 'content')!
    const ready = cats.find((c) => c.key === 'application_ready')!
    expect(content.findings.map((f) => f.label)).toContain('Missing Experience section')
    expect(content.status).toBe('fail')
    expect(ready.findings.length).toBe(1)
  })

  it('routes simulator issues to the right categories', () => {
    const input: ATSCategoryInput = {
      simulatorIssues: [
        { type: 'multi_column', severity: 'high', description: 'Two columns', line_range: 'line 4' },
        { type: 'contact_not_at_top', severity: 'medium', description: 'Contact low', line_range: '' },
        { type: 'no_section_headers', severity: 'high', description: 'No headers', line_range: '' },
      ],
      latexContent: LATEX,
    }
    const cats = buildATSCategories(input)
    const byKey = Object.fromEntries(cats.map((c) => [c.key, c]))
    expect(byKey.format.findings[0].label).toBe('Two columns')
    expect(byKey.best_practices.findings[0].label).toBe('Contact low')
    expect(byKey.application_ready.findings[0].label).toBe('No headers')
  })

  it('flags low keyword match as an Optimization finding, scaling severity', () => {
    const low = buildATSCategories({ quick: { keywordMatchPercent: 20 } }).find((c) => c.key === 'optimization')!
    const mid = buildATSCategories({ quick: { keywordMatchPercent: 50 } }).find((c) => c.key === 'optimization')!
    const ok = buildATSCategories({ quick: { keywordMatchPercent: 80 } }).find((c) => c.key === 'optimization')!
    expect(low.findings[0].severity).toBe('high')
    expect(mid.findings[0].severity).toBe('medium')
    expect(ok.findings.length).toBe(0)
  })

  it('unknown issue types default to Format rather than being dropped', () => {
    const cats = buildATSCategories({
      simulatorIssues: [{ type: 'something_new', severity: 'low', description: 'x', line_range: '' }],
    })
    expect(cats.find((c) => c.key === 'format')!.findings.length).toBe(1)
  })
})

describe('resolveFindingLine', () => {
  it('parses an explicit line_range', () => {
    expect(resolveFindingLine({ type: 'tables', severity: 'high', description: '', line_range: 'line 12' }, LATEX)).toBe(12)
  })

  it('locates contact_not_at_top at the email line', () => {
    expect(resolveFindingLine({ type: 'contact_not_at_top', severity: 'medium', description: '', line_range: '' }, LATEX)).toBe(6)
  })

  it('locates vertical_dates at the first bare-date line', () => {
    expect(resolveFindingLine({ type: 'vertical_dates', severity: 'high', description: '', line_range: '' }, LATEX)).toBe(5)
  })

  it('locates header issues at the first \\section', () => {
    expect(resolveFindingLine({ type: 'no_section_headers', severity: 'high', description: '', line_range: '' }, LATEX)).toBe(3)
  })

  it('returns null when no anchor is found', () => {
    expect(resolveFindingLine({ type: 'skills_not_in_context', severity: 'low', description: '', line_range: '' }, 'no sections here')).toBeNull()
  })
})
