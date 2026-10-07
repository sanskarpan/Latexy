import { describe, expect, it } from 'vitest'
import { DEMO_RESUME_TEMPLATE } from '@/lib/latex-templates'
import { FIRST_USE_RESUME_TEMPLATE } from '@/lib/first-use-resume'
import { addVisualSectionContent, appendVisualSection, projectVisualResume, updateVisualField, visualResumeText } from './visual-projection'

describe('non-destructive visual resume editing', () => {
  it('makes the nontechnical first-use template editable without showing source', () => {
    const projection = projectVisualResume(FIRST_USE_RESUME_TEMPLATE)
    expect(projection.fields.find((field) => field.label === 'Name')?.value).toBe('Alex Morgan')
    expect(projection.fields.filter((field) => field.kind === 'bullet')).toHaveLength(3)
    expect(projection.unsupportedBlocks).toBe(0)
    expect(visualResumeText(FIRST_USE_RESUME_TEMPLATE)).not.toMatch(/\\(?:begin|section|textbf|item|usepackage)/)
  })
  it('projects starred sections and header content without exposing markup', () => {
    const projection = projectVisualResume(DEMO_RESUME_TEMPLATE)
    expect(projection.fields.find((field) => field.label === 'Name')?.value).toBe('Alex Morgan')
    expect(projection.fields.filter((field) => field.kind === 'bullet')).toHaveLength(3)
    expect(projection.fields.some((field) => field.section === 'Skills')).toBe(true)
    expect(visualResumeText(DEMO_RESUME_TEMPLATE)).not.toMatch(/\\(?:section|textbf|item|documentclass)/)
  })

  it('patches only the selected span, escaping user text for compilation', () => {
    const field = projectVisualResume(DEMO_RESUME_TEMPLATE).fields.find((candidate) => candidate.label === 'Name')!
    const updated = updateVisualField(DEMO_RESUME_TEMPLATE, field, 'Taylor & Quinn')
    expect(updated).toBe(DEMO_RESUME_TEMPLATE.replace('Alex Morgan', 'Taylor \\& Quinn'))
    expect(projectVisualResume(updated).fields.find((candidate) => candidate.label === 'Name')?.value).toBe('Taylor & Quinn')
  })

  it('preserves custom macros, nested formatting, comments, preamble and wrappers', () => {
    const source = '\\documentclass{custom}\n\\newcommand{\\secret}{internal}\n\\begin{document}\n\\section{Experience}\n\\resumeSubHeadingListStart\n\\resumeSubheading{Engineer}{2024}{Acme}{Remote}\n\\customlayout{do not touch}\nNormal content % keep this comment\n\\resumeSubHeadingListEnd\n\\end{document}\n% tail'
    const projection = projectVisualResume(source)
    expect(projection.unsupportedBlocks).toBeGreaterThan(0)
    expect(visualResumeText(source)).not.toContain('customlayout')
    expect(visualResumeText(source)).not.toContain('keep this comment')
    const field = projection.fields.find((candidate) => candidate.value === 'Normal content')!
    expect(updateVisualField(source, field, 'Better content')).toBe(source.replace('Normal content', 'Better content'))
  })

  it('rejects stale offsets rather than replacing unrelated source', () => {
    const field = projectVisualResume(DEMO_RESUME_TEMPLATE).fields[0]
    const changed = DEMO_RESUME_TEMPLATE.replace('Alex Morgan', 'Someone Else')
    expect(updateVisualField(changed, field, 'Wrong edit')).toBe(changed)
  })

  it('edits paragraphs without rebuilding the document and supports escaped punctuation', () => {
    const source = '\\begin{document}\n\\section*{Summary}\nEarned 35\\% more\nwith a team of 4.\n\\end{document}'
    const field = projectVisualResume(source).fields.find((candidate) => candidate.label === 'Description')!
    expect(field.value).toBe('Earned 35% more\nwith a team of 4.')
    expect(updateVisualField(source, field, 'Growth: 50% & $20')).toBe(source.replace('Earned 35\\% more\nwith a team of 4.', 'Growth: 50\\% \\& \\$20'))
  })

  it('hides unsupported formatted macro arguments instead of flattening them', () => {
    const source = '\\begin{document}\n\\section{Projects}\n\\resumeProjectHeading{\\textbf{Safe project}}{2025}\n\\resumeItem{\\href{https://example.com}{Custom link}}\n\\end{document}'
    const projection = projectVisualResume(source)
    expect(projection.fields.find((field) => field.value === 'Safe project')).toBeDefined()
    expect(projection.fields.some((field) => field.value.includes('href'))).toBe(false)
    const field = projection.fields.find((candidate) => candidate.value === 'Safe project')!
    expect(updateVisualField(source, field, 'New project')).toBe(source.replace('Safe project', 'New project'))
  })

  it('supports common macro arguments spread across multiple lines', () => {
    const source = '\\begin{document}\n\\section{Experience}\n\\resumeSubheading\n  {Engineer}\n  {2024 -- Present}\n  {Acme}\n  {Remote}\n\\end{document}'
    const projection = projectVisualResume(source)
    expect(projection.fields.map((field) => field.value)).toEqual(['Experience', 'Engineer', '2024 -- Present', 'Acme', 'Remote'])
    const organization = projection.fields.find((field) => field.label === 'Organization')!
    expect(updateVisualField(source, organization, 'New Company')).toBe(source.replace('{Acme}', '{New Company}'))
  })

  it('roundtrips all text punctuation without disappearing or exposing escape commands', () => {
    const field = projectVisualResume(DEMO_RESUME_TEMPLATE).fields.find((candidate) => candidate.label === 'Name')!
    const punctuation = 'Team \\ path ~ approx ^ power % & # _ $ { }'
    const updated = updateVisualField(DEMO_RESUME_TEMPLATE, field, punctuation)
    const projected = projectVisualResume(updated).fields.find((candidate) => candidate.label === 'Name')!
    expect(projected.value).toBe(punctuation)
    expect(projected.value).not.toMatch(/textbackslash|textasciitilde|textasciicircum/)
    expect(updated).toContain('\\textbackslash{}')
    expect(updated).toContain('\\textasciitilde{}')
    expect(updated).toContain('\\textasciicircum{}')
    expect(updateVisualField(updated, projected, 'Updated again')).toBe(DEMO_RESUME_TEMPLATE.replace('Alex Morgan', 'Updated again'))
  })

  it('keeps cleared names and paragraphs editable through subsequent edits', () => {
    for (const label of ['Name', 'Description']) {
      const field = projectVisualResume(FIRST_USE_RESUME_TEMPLATE).fields.find((candidate) => candidate.label === label)!
      const cleared = updateVisualField(FIRST_USE_RESUME_TEMPLATE, field, '')
      const empty = projectVisualResume(cleared).fields.find((candidate) => candidate.id === field.id)!
      expect(empty).toBeDefined()
      expect(empty.value).toBe('')
      expect(visualResumeText(cleared)).not.toContain('mbox')
      const rewritten = updateVisualField(cleared, empty, 'My new content')
      expect(projectVisualResume(rewritten).fields.find((candidate) => candidate.id === field.id)?.value).toBe('My new content')
    }
  })

  it('adds uniquely named sections before the real document ending, preserving comments', () => {
    const source = FIRST_USE_RESUME_TEMPLATE.replace('\\section*{Profile}', '% example: \\end{document}\n\\section*{Profile}')
    const once = appendVisualSection(source)
    const twice = appendVisualSection(once)
    expect(twice).toContain('% example: \\end{document}\n\\section*{Profile}')
    expect(twice).toContain('\\section*{Additional experience}')
    expect(twice).toContain('\\section*{Additional experience 2}')
    expect(twice.indexOf('\\section*{Additional experience 2}')).toBeLessThan(twice.lastIndexOf('\\end{document}'))
  })

  it('adds achievements inside a standard list and prose at a safe section boundary', () => {
    const fields = projectVisualResume(FIRST_USE_RESUME_TEMPLATE).fields
    const experience = fields.find((field) => field.kind === 'heading' && field.value === 'Experience')!
    const added = addVisualSectionContent(FIRST_USE_RESUME_TEMPLATE, experience)
    expect(added.kind).toBe('achievement')
    expect(added.source).toBe(FIRST_USE_RESUME_TEMPLATE.replace('\\end{itemize}', '\\item Describe your achievement here.\n\\end{itemize}'))
    const profile = fields.find((field) => field.kind === 'heading' && field.value === 'Profile')!
    const paragraph = addVisualSectionContent(FIRST_USE_RESUME_TEMPLATE, profile)
    expect(paragraph.kind).toBe('paragraph')
    expect(paragraph.source).toBe(FIRST_USE_RESUME_TEMPLATE.replace('\\section*{Experience}', '\nDescribe your experience here.\n\n\\section*{Experience}'))
  })

  it('does not insert paragraphs into an open custom environment', () => {
    const source = '\\begin{document}\n\\section{Profile}\n\\begin{customlayout}\nKeep this content\n\\section{Experience}\n\\end{customlayout}\n\\end{document}'
    const heading = projectVisualResume(source).fields.find((field) => field.kind === 'heading')!
    expect(addVisualSectionContent(source, heading).source).toBe(source)
  })
})
