import type {
  BuilderMetricsResponse,
  BuilderPreviewResponse,
  StructuredResume,
} from './api-client'

const SAFE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/

export function safeBuilderIdentity(value: string, fallback = 'entry', maxLength = 64): string {
  const raw = String(value || '').trim()
  if (SAFE_ID_RE.test(raw) && raw.length <= maxLength) return raw
  // Keep malformed/imported IDs out of API element keys while remaining
  // deterministic across reloads. The digest prevents two hostile IDs from
  // collapsing onto the same builder identity.
  let hash = 2166136261
  for (let index = 0; index < raw.length; index += 1) hash = Math.imul(hash ^ raw.charCodeAt(index), 16777619)
  const digest = (hash >>> 0).toString(16).padStart(8, '0')
  const prefix = raw.replace(/[^A-Za-z0-9._:-]+/g, '-').replace(/^[.\-:_]+|[.\-:_]+$/g, '')
  const available = Math.max(1, maxLength - digest.length - 1)
  return `${(prefix || fallback).slice(0, available)}-${digest}`
}

function generatedBulletId(entryId: string, index: number, used: Set<string>): string {
  const slot = `-bullet-${index}`
  const base = `${safeBuilderIdentity(entryId, 'entry', Math.max(1, 96 - slot.length))}${slot}`
  let candidate = base
  let counter = 2
  while (used.has(candidate)) {
    const suffix = `-${counter}`
    candidate = `${base.slice(0, 96 - suffix.length)}${suffix}`
    counter += 1
  }
  return candidate
}

export const DEFAULT_STRUCTURED_RESUME: StructuredResume = {
  basics: {
    name: '',
    label: '',
    email: '',
    phone: '',
    location: '',
    website: '',
    linkedin: '',
    github: '',
    summary: '',
  },
  experience: [],
  education: [],
  projects: [],
  skills: [],
  certifications: [],
  awards: [],
  languages: [],
  interests: [],
  section_order: [
    'summary',
    'experience',
    'education',
    'skills',
    'projects',
    'certifications',
    'awards',
    'languages',
    'interests',
  ],
  hidden_sections: [],
}

export function cloneStructuredResume(value?: StructuredResume | null): StructuredResume {
  const cloned = JSON.parse(JSON.stringify(value ?? DEFAULT_STRUCTURED_RESUME)) as StructuredResume
  // Older builder documents predate bullet IDs. Backfill deterministic IDs at
  // load time so changing text does not silently create a new element.
  cloned.experience = cloned.experience.map(entry => ({
    ...entry,
    bullet_ids: reconcileBulletIds(entry.bullets, entry.bullet_ids ?? [], entry.bullets, entry.id),
  }))
  cloned.projects = cloned.projects.map(entry => ({
    ...entry,
    bullet_ids: reconcileBulletIds(entry.bullets, entry.bullet_ids ?? [], entry.bullets, entry.id),
  }))
  return cloned
}

/** Apply a history restore by explicit structured identity, never by parsing
 * the display/API key (IDs themselves may contain colons). */
export function applyRestoredBullet(
  structured: StructuredResume,
  section: 'experience' | 'project',
  entryId: string,
  bulletId: string,
  content: string,
  expectedCurrentContent?: string,
): boolean {
  const entries = section === 'experience' ? structured.experience : structured.projects
  const entry = entries.find(item => item.id === entryId)
  const bulletIndex = entry?.bullet_ids.indexOf(bulletId) ?? -1
  if (!entry || bulletIndex < 0 || bulletIndex >= entry.bullets.length) return false
  if (expectedCurrentContent !== undefined && entry.bullets[bulletIndex] !== expectedCurrentContent) return false
  entry.bullets[bulletIndex] = content
  return true
}

export function createBuilderId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * Reconcile structured bullet IDs through textarea edits. Exact surrounding
 * lines are anchors; unmatched slots pair positionally (an edit), while true
 * insertions receive collision-safe fresh IDs. This keeps IDs out of mutable
 * text while avoiding the old positional-ID migration bug.
 */
export function reconcileBulletIds(
  previousBullets: string[],
  previousIds: string[],
  nextBullets: string[],
  entryId: string,
): string[] {
  const normalizedPrevious = previousBullets.map(value => value.trim())
  const normalizedNext = nextBullets.map(value => value.trim())
  const result = Array<string>(nextBullets.length).fill('')
  const used = new Set<string>()
  const safePreviousIds: string[] = []
  const previousUsed = new Set<string>()
  previousIds.forEach((id, index) => {
    const candidate = typeof id === 'string' && SAFE_ID_RE.test(id.trim()) ? id.trim() : generatedBulletId(entryId, index, previousUsed)
    const resolved = previousUsed.has(candidate) ? generatedBulletId(entryId, index, previousUsed) : candidate
    previousUsed.add(resolved)
    safePreviousIds.push(resolved)
  })
  const assign = (nextIndex: number, candidate: string) => {
    if (!candidate || used.has(candidate)) return false
    result[nextIndex] = candidate; used.add(candidate); return true
  }
  // First map exact text globally (including reorders and duplicate lines by
  // occurrence), then pair remaining slots positionally as edits.
  const available = new Map<string, number[]>()
  normalizedPrevious.forEach((value, index) => {
    const bucket = available.get(value) ?? []
    bucket.push(index)
    available.set(value, bucket)
  })
  const usedOld = new Set<number>()
  normalizedNext.forEach((value, index) => {
    const bucket = available.get(value)
    const oldIndex = bucket?.shift()
    if (oldIndex !== undefined) {
      usedOld.add(oldIndex)
      assign(index, safePreviousIds[oldIndex])
    }
  })
  const unmatchedOld = safePreviousIds.map((_, index) => index).filter(index => !usedOld.has(index))
  const unmatchedNext = result.map((id, index) => index).filter((_, index) => !result[index])
  for (let index = 0; index < Math.min(unmatchedOld.length, unmatchedNext.length); index += 1) {
    assign(unmatchedNext[index], safePreviousIds[unmatchedOld[index]])
  }
  for (const newIndex of unmatchedNext.slice(unmatchedOld.length)) {
    let candidate = generatedBulletId(entryId, newIndex, used)
    while (used.has(candidate)) candidate = `${candidate.slice(0, 86)}-${createBuilderId('id').slice(-8)}`
    assign(newIndex, candidate)
  }
  // Empty/duplicate edge cases still receive unique IDs.
  return result.map((id, index) => {
    if (id) return id
    let candidate = generatedBulletId(entryId, index, used)
    while (used.has(candidate)) candidate = `${candidate.slice(0, 86)}-${createBuilderId('id').slice(-8)}`
    used.add(candidate)
    return candidate
  })
}

function joinMeta(...parts: Array<string | undefined>) {
  return parts.map(part => part?.trim()).filter(Boolean).join(' | ')
}

function dateRange(start: string, end: string, current = false) {
  const from = start.trim()
  const to = current ? 'Present' : end.trim()
  if (!from && !to) return ''
  if (!from) return to
  if (!to) return from
  return `${from} - ${to}`
}

export function deriveBuilderMetrics(structured: StructuredResume): BuilderMetricsResponse {
  const hidden = new Set(structured.hidden_sections)
  const hasText = (value: string) => Boolean(value.trim())
  const experience = hidden.has('experience') ? [] : structured.experience.filter(item =>
    [item.title, item.company, item.summary, ...item.bullets, ...item.technologies].some(hasText))
  const education = hidden.has('education') ? [] : structured.education.filter(item =>
    [item.institution, item.degree, item.field, ...item.highlights].some(hasText))
  const skills = hidden.has('skills') ? [] : structured.skills.filter(item => item.keywords.some(hasText))
  const projects = hidden.has('projects') ? [] : structured.projects.filter(item =>
    [item.name, item.description, ...item.bullets, ...item.technologies].some(hasText))
  let score = 0
  const missing: string[] = []
  const warnings: string[] = []

  if (structured.basics.name.trim()) score += 15
  else missing.push('name')

  if (structured.basics.email.trim()) score += 10
  else missing.push('email')

  if (!hidden.has('summary')) {
    if (structured.basics.summary.trim()) score += 10
    else missing.push('summary')
  }

  if (experience.length) score += 25
  else if (!hidden.has('experience')) missing.push('experience')

  if (education.length) score += 15
  else if (!hidden.has('education')) missing.push('education')

  if (skills.length) score += 15
  else if (!hidden.has('skills')) missing.push('skills')

  if (projects.length) score += 10

  let totalLines = 6
  totalLines += Object.entries(structured.basics).filter(([key, value]) => key !== 'summary' && typeof value === 'string' && value.trim()).length
  if (!hidden.has('summary')) totalLines += structured.basics.summary.split('\n').filter(hasText).length
  totalLines += experience.reduce((sum, entry) => sum + Math.max(3, entry.bullets.filter(hasText).length + 2), 0)
  totalLines += education.reduce((sum, entry) => sum + Math.max(2, entry.highlights.filter(hasText).length + 1), 0)
  totalLines += skills.reduce((sum, group) => sum + Math.max(2, Math.ceil(group.keywords.filter(hasText).length / 5) + 1), 0)
  totalLines += projects.reduce((sum, project) => sum + Math.max(2, project.bullets.filter(hasText).length + 2), 0)
  if (!hidden.has('certifications')) totalLines += structured.certifications.filter(item => [item.name, item.issuer, item.date, item.url].some(hasText)).length
  for (const key of ['awards', 'languages', 'interests'] as const) {
    if (!hidden.has(key)) totalLines += structured[key].filter(item => item.name.trim() || item.detail.trim()).length
  }

  const pageEstimate = Math.max(1, Math.floor((totalLines + 37) / 38))
  if (pageEstimate > 1) warnings.push('Content likely exceeds one page in compact templates.')
  if (experience.some(entry => entry.bullets.filter(hasText).length > 6)) warnings.push('Some experience entries are dense; consider trimming bullets.')
  if (!structured.basics.label.trim()) warnings.push('Add a headline to improve clarity at the top of the resume.')

  return {
    completeness_score: Math.min(score, 100),
    page_estimate: pageEstimate,
    warnings,
    missing_sections: missing,
  }
}

export function deriveBuilderPreview(
  structured: StructuredResume,
  templateFamily: string,
): BuilderPreviewResponse {
  const hidden = new Set(structured.hidden_sections)
  const sections: BuilderPreviewResponse['sections'] = []

  for (const section of structured.section_order) {
    if (hidden.has(section)) continue

    if (section === 'summary' && structured.basics.summary.trim()) {
      sections.push({
        key: 'summary',
        title: 'Summary',
        items: [structured.basics.summary.trim()],
      })
    } else if (section === 'experience' && structured.experience.length) {
      sections.push({
        key: 'experience',
        title: 'Experience',
        items: structured.experience
          .filter(item => [item.title, item.company, item.summary, ...item.bullets, ...item.technologies].some(value => value.trim()))
          .map(item => ({
            title: `${item.title} — ${item.company}`.trim().replace(/^—\s*/, '').replace(/\s+—$/, ''),
            meta: joinMeta(item.location, dateRange(item.start_date, item.end_date, item.current), item.technologies.some(value => value.trim()) ? `Technologies: ${item.technologies.filter(value => value.trim()).join(', ')}` : ''),
            bullets: [item.summary, ...item.bullets].filter(value => value.trim()),
          })),
      })
    } else if (section === 'education' && structured.education.length) {
      sections.push({
        key: 'education',
        title: 'Education',
        items: structured.education
          .filter(item => [item.institution, item.degree, item.field, ...item.highlights].some(value => value.trim()))
          .map(item => ({
            title: `${joinMeta(item.degree, item.field)} — ${item.institution}`.trim().replace(/^—\s*/, '').replace(/\s+—$/, ''),
            meta: joinMeta(item.location, dateRange(item.start_date, item.end_date), item.gpa.trim() ? `GPA ${item.gpa}` : ''),
            bullets: item.highlights.filter(value => value.trim()),
          })),
      })
    } else if (section === 'skills' && structured.skills.length) {
      sections.push({
        key: 'skills',
        title: 'Skills',
        items: structured.skills
          .filter(item => item.keywords.some(value => value.trim()))
          .map(item => ({
            title: item.name,
            meta: item.keywords.filter(value => value.trim()).join(', '),
          })),
      })
    } else if (section === 'projects' && structured.projects.length) {
      sections.push({
        key: 'projects',
        title: 'Projects',
        items: structured.projects
          .filter(item => [item.name, item.description, ...item.bullets, ...item.technologies].some(value => value.trim()))
          .map(item => ({
            title: item.name,
            meta: joinMeta(item.role, item.url, dateRange(item.start_date, item.end_date), item.technologies.some(value => value.trim()) ? `Technologies: ${item.technologies.filter(value => value.trim()).join(', ')}` : ''),
            bullets: [item.description, ...item.bullets].filter(value => value.trim()),
          })),
      })
    } else if (section === 'certifications' && structured.certifications.length) {
      sections.push({
        key: 'certifications',
        title: 'Certifications',
        items: structured.certifications
          .filter(item => [item.name, item.issuer, item.date, item.url].some(value => value.trim()))
          .map(item => ({
            title: item.name,
            meta: joinMeta(item.issuer, item.date, item.url),
          })),
      })
    } else if (section === 'awards' && structured.awards.length) {
      sections.push({
        key: 'awards',
        title: 'Awards',
        items: structured.awards
          .filter(item => item.name.trim() || item.detail.trim())
          .map(item => ({
            title: item.name,
            meta: item.detail,
          })),
      })
    } else if (section === 'languages' && structured.languages.length) {
      sections.push({
        key: 'languages',
        title: 'Languages',
        items: structured.languages
          .filter(item => item.name.trim() || item.detail.trim())
          .map(item => ({
            title: item.name,
            meta: item.detail,
          })),
      })
    } else if (section === 'interests' && structured.interests.length) {
      sections.push({
        key: 'interests',
        title: 'Interests',
        items: structured.interests
          .filter(item => item.name.trim() || item.detail.trim())
          .map(item => ({
            title: item.name,
            meta: item.detail,
          })),
      })
    }
  }

  return {
    template_family: templateFamily,
    sections: sections.filter(section => section.items.length > 0),
  }
}
