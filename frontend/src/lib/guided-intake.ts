/**
 * Guided-intake direction for AI optimization (input-driven optimization, PRD
 * 2026-08-02). Pure types + helpers, kept free of React/JSX so they can be unit
 * tested and reused by the api-client mapping. The UI lives in
 * `components/GuidedIntakePanel.tsx`.
 */

export interface GuidedIntake {
  industry: string
  seniority: string
  tone: string
  emphasize: string[]
  downplay: string[]
}

export const EMPTY_INTAKE: GuidedIntake = {
  industry: '',
  seniority: '',
  tone: '',
  emphasize: [],
  downplay: [],
}

export const SENIORITY_OPTIONS = [
  'Intern',
  'Junior',
  'Mid',
  'Senior',
  'Staff / Lead',
  'Manager',
  'Director+',
]

export const TONE_OPTIONS = [
  'Confident & concise',
  'Impact-focused',
  'Technical',
  'Formal',
  'Conversational',
]

export function intakeIsEmpty(v: GuidedIntake): boolean {
  return (
    !v.industry.trim() &&
    !v.seniority.trim() &&
    !v.tone.trim() &&
    v.emphasize.length === 0 &&
    v.downplay.length === 0
  )
}

/** Count of populated direction fields — drives the "active" badge. */
export function intakeActiveCount(v: GuidedIntake): number {
  return (
    (v.industry.trim() ? 1 : 0) +
    (v.seniority.trim() ? 1 : 0) +
    (v.tone.trim() ? 1 : 0) +
    (v.emphasize.length ? 1 : 0) +
    (v.downplay.length ? 1 : 0)
  )
}
