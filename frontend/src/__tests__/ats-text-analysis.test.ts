import { describe, test, expect } from 'vitest'
import {
  LIGATURE_RE,
  COLUMN_GARBLE_RE,
  detectSections,
  hasLigatureGarbling,
  hasColumnGarbling,
  SECTION_PATTERNS,
} from '../lib/ats-text-analysis'

// ─── LIGATURE_RE ──────────────────────────────────────────────────────────────

describe('LIGATURE_RE', () => {
  test('matches ﬁ (fi ligature)', () => {
    expect(LIGATURE_RE.test('proﬁle')).toBe(true)
  })

  test('matches ﬀ (ff ligature)', () => {
    expect(LIGATURE_RE.test('oﬀice')).toBe(true)
  })

  test('matches ﬂ (fl ligature)', () => {
    expect(LIGATURE_RE.test('reﬂect')).toBe(true)
  })

  test('matches ﬃ (ffi ligature)', () => {
    expect(LIGATURE_RE.test('eﬃcient')).toBe(true)
  })

  test('does not match plain ASCII text', () => {
    expect(LIGATURE_RE.test('profile office reflect')).toBe(false)
  })

  test('does not match empty string', () => {
    expect(LIGATURE_RE.test('')).toBe(false)
  })
})

// ─── hasLigatureGarbling ──────────────────────────────────────────────────────

describe('hasLigatureGarbling', () => {
  test('returns true for text with ligature characters', () => {
    expect(hasLigatureGarbling('John Doe\nSoftware Engineer\nproﬁle summary')).toBe(true)
  })

  test('returns false for clean extracted text', () => {
    expect(hasLigatureGarbling('John Doe\nSoftware Engineer\nprofile summary')).toBe(false)
  })

  test('returns false for empty string', () => {
    expect(hasLigatureGarbling('')).toBe(false)
  })
})

// ─── COLUMN_GARBLE_RE ─────────────────────────────────────────────────────────

describe('COLUMN_GARBLE_RE', () => {
  test('matches line merging contact info and experience keyword', () => {
    expect(COLUMN_GARBLE_RE.test('john@example.com experience engineer')).toBe(true)
  })

  test('matches phone number with education keyword on same line', () => {
    expect(COLUMN_GARBLE_RE.test('+1-555-0100 education university')).toBe(true)
  })

  test('does not match normal contact info line alone', () => {
    expect(COLUMN_GARBLE_RE.test('john@example.com')).toBe(false)
  })

  test('does not match experience section header alone', () => {
    expect(COLUMN_GARBLE_RE.test('EXPERIENCE')).toBe(false)
  })

  test('is case-insensitive', () => {
    expect(COLUMN_GARBLE_RE.test('john@example.com EXPERIENCE')).toBe(true)
  })
})

// ─── hasColumnGarbling ────────────────────────────────────────────────────────

describe('hasColumnGarbling', () => {
  test('returns true when contact token and section header are on same line', () => {
    const garbled = 'john@example.com experience\nSoftware Engineer'
    expect(hasColumnGarbling(garbled)).toBe(true)
  })

  test('returns false for clean single-column layout', () => {
    const clean = [
      'John Doe',
      'john@example.com',
      '',
      'EXPERIENCE',
      'Software Engineer at Acme Corp',
    ].join('\n')
    expect(hasColumnGarbling(clean)).toBe(false)
  })
})

// ─── detectSections ───────────────────────────────────────────────────────────

describe('detectSections', () => {
  test('detects Contact Info from email address', () => {
    expect(detectSections('john@example.com')).toContain('Contact Info')
  })

  test('detects Contact Info from linkedin keyword', () => {
    expect(detectSections('linkedin.com/in/johndoe')).toContain('Contact Info')
  })

  test('detects Experience section', () => {
    expect(detectSections('EXPERIENCE\nSoftware Engineer')).toContain('Experience')
  })

  test('detects Education section', () => {
    expect(detectSections('EDUCATION\nBachelor of Science')).toContain('Education')
  })

  test('detects Education from university keyword', () => {
    expect(detectSections('MIT University')).toContain('Education')
  })

  test('detects Skills section', () => {
    expect(detectSections('SKILLS\nPython, TypeScript')).toContain('Skills')
  })

  test('detects Projects section', () => {
    expect(detectSections('PROJECTS\nOpen source contributions')).toContain('Projects')
  })

  test('detects Summary section', () => {
    expect(detectSections('SUMMARY\nExperienced engineer')).toContain('Summary')
  })

  test('detects multiple sections from a realistic resume', () => {
    const text = [
      'John Doe',
      'john@example.com | linkedin.com/in/john',
      '',
      'SUMMARY',
      'Experienced software engineer with 5 years.',
      '',
      'EXPERIENCE',
      'Software Engineer, Acme Corp 2019–2024',
      '',
      'EDUCATION',
      'B.S. Computer Science, MIT 2015–2019',
      '',
      'SKILLS',
      'Python TypeScript React PostgreSQL',
    ].join('\n')
    const sections = detectSections(text)
    expect(sections).toContain('Contact Info')
    expect(sections).toContain('Summary')
    expect(sections).toContain('Experience')
    expect(sections).toContain('Education')
    expect(sections).toContain('Skills')
  })

  test('returns empty array for plain text with no recognisable sections', () => {
    expect(detectSections('Lorem ipsum dolor sit amet.')).toEqual([])
  })

  test('returns empty array for empty string', () => {
    expect(detectSections('')).toEqual([])
  })

  test('detection is case-insensitive', () => {
    expect(detectSections('EXPERIENCE')).toContain('Experience')
    expect(detectSections('experience')).toContain('Experience')
    expect(detectSections('Experience')).toContain('Experience')
  })
})

// ─── SECTION_PATTERNS completeness ───────────────────────────────────────────

describe('SECTION_PATTERNS', () => {
  test('has 6 defined sections', () => {
    expect(SECTION_PATTERNS).toHaveLength(6)
  })

  test('every pattern has a label and a RegExp', () => {
    for (const { label, re } of SECTION_PATTERNS) {
      expect(typeof label).toBe('string')
      expect(label.length).toBeGreaterThan(0)
      expect(re).toBeInstanceOf(RegExp)
    }
  })
})
