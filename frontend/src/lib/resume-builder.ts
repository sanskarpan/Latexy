import type {
  BuilderMetricsResponse,
  BuilderPreviewResponse,
  StructuredResume,
} from './api-client'

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
  return JSON.parse(JSON.stringify(value ?? DEFAULT_STRUCTURED_RESUME)) as StructuredResume
}

export function createBuilderId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`
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
  let score = 0
  const missing: string[] = []
  const warnings: string[] = []

  if (structured.basics.name.trim()) score += 15
  else missing.push('name')

  if (structured.basics.email.trim()) score += 10
  else missing.push('email')

  if (structured.basics.summary.trim()) score += 10
  else missing.push('summary')

  if (structured.experience.length) score += 25
  else missing.push('experience')

  if (structured.education.length) score += 15
  else missing.push('education')

  if (structured.skills.some(group => group.keywords.length)) score += 15
  else missing.push('skills')

  if (structured.projects.length) score += 10

  let totalLines = 6
  totalLines += Object.values(structured.basics).filter(value => typeof value === 'string' && value.trim()).length
  totalLines += structured.basics.summary.split('\n').filter(Boolean).length
  totalLines += structured.experience.reduce((sum, entry) => sum + Math.max(3, entry.bullets.filter(Boolean).length + 2), 0)
  totalLines += structured.education.reduce((sum, entry) => sum + Math.max(2, entry.highlights.filter(Boolean).length + 1), 0)
  totalLines += structured.skills.reduce((sum, group) => sum + Math.max(2, Math.ceil(group.keywords.length / 5) + 1), 0)
  totalLines += structured.projects.reduce((sum, project) => sum + Math.max(2, project.bullets.filter(Boolean).length + 2), 0)

  const pageEstimate = Math.max(1, Math.floor((totalLines + 37) / 38))
  if (pageEstimate > 1) warnings.push('Content likely exceeds one page in compact templates.')
  if (structured.experience.some(entry => entry.bullets.length > 6)) warnings.push('Some experience entries are dense; consider trimming bullets.')
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
          .filter(item => item.title.trim() || item.company.trim() || item.bullets.some(Boolean))
          .map(item => ({
            title: `${item.title} — ${item.company}`.trim().replace(/^—\s*/, '').replace(/\s+—$/, ''),
            meta: joinMeta(item.location, dateRange(item.start_date, item.end_date, item.current)),
            bullets: [item.summary, ...item.bullets].filter(value => value.trim()),
          })),
      })
    } else if (section === 'education' && structured.education.length) {
      sections.push({
        key: 'education',
        title: 'Education',
        items: structured.education
          .filter(item => item.institution.trim() || item.degree.trim())
          .map(item => ({
            title: `${item.degree} — ${item.institution}`.trim().replace(/^—\s*/, '').replace(/\s+—$/, ''),
            meta: joinMeta(item.location, dateRange(item.start_date, item.end_date)),
            bullets: item.highlights.filter(value => value.trim()),
          })),
      })
    } else if (section === 'skills' && structured.skills.length) {
      sections.push({
        key: 'skills',
        title: 'Skills',
        items: structured.skills
          .filter(item => item.name.trim() || item.keywords.length)
          .map(item => ({
            title: item.name,
            meta: item.keywords.join(', '),
          })),
      })
    } else if (section === 'projects' && structured.projects.length) {
      sections.push({
        key: 'projects',
        title: 'Projects',
        items: structured.projects
          .filter(item => item.name.trim() || item.description.trim() || item.bullets.some(Boolean))
          .map(item => ({
            title: item.name,
            meta: joinMeta(item.role, item.url, dateRange(item.start_date, item.end_date)),
            bullets: [item.description, ...item.bullets].filter(value => value.trim()),
          })),
      })
    } else if (section === 'certifications' && structured.certifications.length) {
      sections.push({
        key: 'certifications',
        title: 'Certifications',
        items: structured.certifications
          .filter(item => item.name.trim() || item.issuer.trim() || item.date.trim())
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
    sections,
  }
}
