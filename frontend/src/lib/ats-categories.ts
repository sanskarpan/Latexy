/**
 * ATS multi-dimensional score card (#1367).
 *
 * The backend hands us three cheap, rule-based signals — the quick score
 * (sections + keyword match), and the Textkernel-coded simulator issues
 * (#1289/#1585). This module folds them into the five named categories a
 * candidate recognises (Rezi's taxonomy) and resolves each finding to a
 * best-effort editor line so the card can deep-link back into the builder.
 *
 * Pure and framework-free so it can be unit-tested without React.
 */

export type ATSCategoryKey =
  | 'content'
  | 'format'
  | 'optimization'
  | 'best_practices'
  | 'application_ready'

export type ATSCategoryStatus = 'good' | 'warn' | 'fail'
export type ATSSeverity = 'high' | 'medium' | 'low'

export interface ATSFinding {
  /** Stable key for React lists. */
  id: string
  /** One-line, candidate-facing description of the problem. */
  label: string
  severity: ATSSeverity
  /** 1-indexed editor line to jump to on click, or null when not locatable. */
  line: number | null
  /** Where/how to fix, shown when there is no line to jump to. */
  hint?: string
}

export interface ATSCategory {
  key: ATSCategoryKey
  label: string
  status: ATSCategoryStatus
  findings: ATSFinding[]
}

export interface QuickScoreSignal {
  grade?: string | null
  sectionsFound?: string[]
  missingSections?: string[]
  keywordMatchPercent?: number | null
}

export interface SimulatorIssueSignal {
  type: string
  severity: string
  description: string
  line_range?: string
}

export interface ATSCategoryInput {
  quick?: QuickScoreSignal | null
  simulatorIssues?: SimulatorIssueSignal[] | null
  /** The current editor content, used to locate document-level findings. */
  latexContent?: string
}

export const ATS_CATEGORY_LABELS: Record<ATSCategoryKey, string> = {
  content: 'Content',
  format: 'Format',
  optimization: 'Optimization',
  best_practices: 'Best Practices',
  application_ready: 'Application Ready',
}

const CATEGORY_ORDER: ATSCategoryKey[] = [
  'content',
  'format',
  'optimization',
  'best_practices',
  'application_ready',
]

/**
 * Which category each simulator issue type belongs to.
 *  - Format:            layout/parsing cleanliness a machine reads
 *  - Best Practices:    résumé conventions (headers, contact placement)
 *  - Application Ready: fatal blockers that stop a parser cold
 */
const ISSUE_CATEGORY: Record<string, ATSCategoryKey> = {
  // Format
  multi_column: 'format',
  tables: 'format',
  decorative_elements: 'format',
  complex_layouts: 'format',
  pdf_formatting: 'format',
  vertical_dates: 'format',
  // Best Practices
  custom_sections: 'best_practices',
  contact_not_at_top: 'best_practices',
  nonstandard_section_headers: 'best_practices',
  skills_not_in_context: 'best_practices',
  // Application Ready (fatal)
  no_section_headers: 'application_ready',
  contact_missing: 'application_ready',
}

const _EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/
const _PHONE_RE = /(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/
const _SECTION_CMD_RE = /\\[a-zA-Z]*section\*?\s*\{/
const _BARE_DATE_RE = /^\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(?:19|20)\d{2}\s*$/i

function normalizeSeverity(raw: string): ATSSeverity {
  const s = (raw || '').toLowerCase()
  if (s === 'high' || s === 'fatal') return 'high'
  if (s === 'medium' || s === 'major') return 'medium'
  return 'low'
}

/** 1-indexed line of the first content line matching `re`, or null. */
function findLine(latex: string, re: RegExp): number | null {
  const lines = latex.split('\n')
  for (let i = 0; i < lines.length; i++) {
    if (re.test(lines[i])) return i + 1
  }
  return null
}

/**
 * Best-effort editor line for a finding. Structural issues carry an explicit
 * `line_range` ("line 12"); document-level Textkernel checks do not, so we
 * locate a sensible anchor from the content instead.
 */
export function resolveFindingLine(issue: SimulatorIssueSignal, latex: string): number | null {
  const explicit = issue.line_range?.match(/(\d+)/)
  if (explicit) return parseInt(explicit[1], 10)
  if (!latex) return null

  switch (issue.type) {
    case 'contact_not_at_top':
      return findLine(latex, _EMAIL_RE) ?? findLine(latex, _PHONE_RE)
    case 'vertical_dates':
      return findLine(latex, _BARE_DATE_RE)
    case 'no_section_headers':
    case 'nonstandard_section_headers':
    case 'skills_not_in_context':
      return findLine(latex, _SECTION_CMD_RE)
    default:
      return null
  }
}

function statusFromFindings(findings: ATSFinding[]): ATSCategoryStatus {
  if (findings.some((f) => f.severity === 'high')) return 'fail'
  if (findings.length > 0) return 'warn'
  return 'good'
}

/** Title-case a snake/lower section name for display ("work_experience" → "Work Experience"). */
function humanizeSection(name: string): string {
  return name
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim()
}

/**
 * Fold the available ATS signals into the five named categories.
 * Categories are always returned in a stable order, even when empty (a clean
 * clean category renders as "good" — reassurance, not a blank).
 */
export function buildATSCategories(input: ATSCategoryInput): ATSCategory[] {
  const latex = input.latexContent ?? ''
  const byCategory: Record<ATSCategoryKey, ATSFinding[]> = {
    content: [],
    format: [],
    optimization: [],
    best_practices: [],
    application_ready: [],
  }

  // Quick-score signals → Content, Optimization, Application Ready.
  const quick = input.quick
  if (quick) {
    for (const missing of quick.missingSections ?? []) {
      const finding: ATSFinding = {
        id: `missing:${missing}`,
        label: `Missing ${humanizeSection(missing)} section`,
        severity: 'high',
        line: findLine(latex, _SECTION_CMD_RE),
        hint: `Add a ${humanizeSection(missing)} section with a clear header.`,
      }
      // A missing required section is both a content gap and a submission blocker.
      byCategory.content.push(finding)
      byCategory.application_ready.push({ ...finding, id: `ready-${finding.id}` })
    }

    const kw = quick.keywordMatchPercent
    if (typeof kw === 'number' && kw < 60) {
      byCategory.optimization.push({
        id: 'keyword-coverage',
        label: `Low keyword match with the job description (${Math.round(kw)}%)`,
        severity: kw < 35 ? 'high' : 'medium',
        line: null,
        hint: 'Mirror the job description’s key terms in your Skills and Experience.',
      })
    }
  }

  // Simulator issues → Format / Best Practices / Application Ready.
  for (let i = 0; i < (input.simulatorIssues ?? []).length; i++) {
    const issue = input.simulatorIssues![i]
    const category = ISSUE_CATEGORY[issue.type] ?? 'format'
    byCategory[category].push({
      id: `sim:${issue.type}:${i}`,
      label: issue.description,
      severity: normalizeSeverity(issue.severity),
      line: resolveFindingLine(issue, latex),
    })
  }

  return CATEGORY_ORDER.map((key) => ({
    key,
    label: ATS_CATEGORY_LABELS[key],
    status: statusFromFindings(byCategory[key]),
    findings: byCategory[key],
  }))
}
