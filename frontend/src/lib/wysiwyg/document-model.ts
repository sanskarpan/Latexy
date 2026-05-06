/**
 * Intermediate Representation (IR) for the WYSIWYG editor (Feature 78).
 *
 * A `ResumeDoc` is the canonical document model that lives between the LaTeX
 * source (on the left) and the visual form editor (on the right).
 */

export type EntryType =
  | 'subheading'     // \resumeSubheading — job / education entry with 4 fields
  | 'project'        // \resumeProjectHeading — project entry with heading + dates
  | 'cventry'        // \cventry — AltaCV-style entry
  | 'cvevent'        // \cvevent — AltaCV-style event entry
  | 'bullets'        // standalone \begin{itemize} block
  | 'raw'            // unrecognised / verbatim block

export interface Entry {
  /** Original macro name (e.g. "resumeSubheading", "resumeProjectHeading") — used for round-trip fidelity */
  macro?: string
  type: EntryType
  /** Primary heading / title */
  heading?: string
  /** Secondary heading / company / institution */
  subheading?: string
  startDate?: string
  endDate?: string
  location?: string
  /** Raw latex lines for verbatim blocks */
  raw?: string
  bullets: string[]
}

export interface Section {
  title: string
  entries: Entry[]
}

export interface ResumeDoc {
  /** Pre-body preamble (before first \section) */
  preamble: string
  sections: Section[]
  /** Post-body epilogue (after last \end{document} equivalent) */
  epilogue: string
}

export interface ParseWarning {
  type: 'unrecognised_block' | 'parse_error'
  message: string
  raw?: string
}

export interface ParseResult {
  doc: ResumeDoc
  warnings: ParseWarning[]
}
