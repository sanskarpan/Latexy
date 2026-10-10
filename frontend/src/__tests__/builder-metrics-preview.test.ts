import { describe, expect, it } from 'vitest'
import { cloneStructuredResume, deriveBuilderMetrics, deriveBuilderPreview } from '@/lib/resume-builder'

function document() {
  const doc = cloneStructuredResume()
  doc.experience.push({ id: 'role', title: '', company: '', location: '', start_date: '', end_date: '', current: false, summary: '', bullets: [' '], bullet_ids: ['bullet'], technologies: [' '] })
  doc.education.push({ id: 'school', institution: '', degree: '', field: '', location: '', start_date: '', end_date: '', gpa: '', highlights: [' '] })
  doc.projects.push({ id: 'project', name: '', role: '', url: '', start_date: '', end_date: '', description: '', bullets: [' '], bullet_ids: ['bullet'], technologies: [' '] })
  doc.skills.push({ id: 'skills', name: 'Core', keywords: [' '] })
  return doc
}

describe('builder content progress and preview', () => {
  it('does not reward empty cards or display their headings', () => {
    const doc = document()
    expect(deriveBuilderMetrics(doc).completeness_score).toBe(0)
    expect(deriveBuilderMetrics(doc).page_estimate).toBe(1)
    expect(deriveBuilderPreview(doc, 'minimal').sections).toEqual([])
  })
  it('preserves custom titles while omitting empty and hidden sections', () => {
    const doc = document()
    doc.experience[0].title = 'Associate'
    doc.education[0].institution = 'Example University'
    doc.projects[0].name = 'Hidden project'
    doc.hidden_sections = ['projects']
    doc.section_titles = {
      experience: '  Work History  ',
      education: '   ',
      skills: 'Expertise',
      projects: 'Selected Projects',
    }

    const preview = deriveBuilderPreview(doc, 'minimal')
    expect(preview.sections.map(({ key, title }) => ({ key, title }))).toEqual([
      { key: 'experience', title: 'Work History' },
      { key: 'education', title: 'Education' },
    ])
    expect(preview.sections.every(section => section.items.length > 0)).toBe(true)
    expect(deriveBuilderMetrics(doc).completeness_score).toBe(40)
  })
  it('excludes hidden content from progress, warnings and estimated pages', () => {
    const doc = document()
    doc.basics.name = 'Alex'
    doc.basics.email = 'alex@example.com'
    doc.experience[0].title = 'Associate'
    doc.experience[0].bullets = Array.from({ length: 80 }, () => 'Customer support')
    doc.hidden_sections = ['experience']
    const metrics = deriveBuilderMetrics(doc)
    expect(metrics.completeness_score).toBe(25)
    expect(metrics.page_estimate).toBe(1)
    expect(metrics.missing_sections).not.toContain('experience')
    expect(metrics.warnings).not.toContain('Some experience entries are dense; consider trimming bullets.')
  })
  it('includes technologies, education field and GPA in the content preview', () => {
    const doc = document()
    doc.experience[0].title = 'Associate'
    doc.experience[0].summary = 'Customer support'
    doc.experience[0].technologies = ['Zendesk', ' ']
    Object.assign(doc.education[0], { degree: 'B.A.', field: 'Communication', institution: 'Example University', gpa: '3.8' })
    const preview = deriveBuilderPreview(doc, 'minimal')
    expect(preview.sections[0].items[0]).toMatchObject({ meta: 'Technologies: Zendesk', bullets: ['Customer support'] })
    expect(preview.sections[1].items[0]).toMatchObject({ title: 'B.A. | Communication — Example University', meta: 'GPA 3.8' })
  })
})
