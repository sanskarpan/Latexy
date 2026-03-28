/**
 * Pure utility functions for ATS text analysis.
 * Extracted from ATSTextView so they can be unit-tested without a DOM.
 */

// ─── Garbling detectors ───────────────────────────────────────────────────────

/**
 * Unicode ligature characters that indicate pdftotext failed to decode them.
 * These appear when a PDF is compiled without \input{glyphtounicode}.
 * fi, ff, fl, ffi, ffl, ſt, st ligatures.
 */
export const LIGATURE_RE = /[ﬀﬁﬂﬃﬄﬅﬆ]/

/**
 * Detects possible two-column layout garbling: a line that contains both
 * contact-info tokens (email/phone marker) and section-header keywords
 * on the same line — indicating left and right columns were merged.
 */
export const COLUMN_GARBLE_RE = /[@+]\S+.*(?:experience|education|skills|work|employment)/i

// ─── Section detection ────────────────────────────────────────────────────────

export interface SectionDef {
  label: string
  re: RegExp
}

export const SECTION_PATTERNS: SectionDef[] = [
  { label: 'Contact Info',   re: /\b(email|phone|linkedin|github|@[^\s]+)\b/i },
  { label: 'Experience',     re: /\b(experience|employment|work history)\b/i },
  { label: 'Education',      re: /\b(education|university|college|degree|bachelor|master|phd)\b/i },
  { label: 'Skills',         re: /\b(skills|technologies|proficiencies|languages)\b/i },
  { label: 'Projects',       re: /\b(projects?|open.?source)\b/i },
  { label: 'Summary',        re: /\b(summary|objective|profile|about)\b/i },
]

/** Returns the labels of sections detected in the extracted text. */
export function detectSections(text: string): string[] {
  return SECTION_PATTERNS.filter(({ re }) => re.test(text)).map(({ label }) => label)
}

/** Returns true if the text contains Unicode ligature characters. */
export function hasLigatureGarbling(text: string): boolean {
  return LIGATURE_RE.test(text)
}

/** Returns true if the text shows signs of two-column layout merging. */
export function hasColumnGarbling(text: string): boolean {
  return COLUMN_GARBLE_RE.test(text)
}
