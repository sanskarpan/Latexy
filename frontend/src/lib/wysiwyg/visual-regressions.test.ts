import { describe, expect, it } from 'vitest'
import { FIRST_USE_RESUME_TEMPLATE } from '@/lib/first-use-resume'
import { addVisualSectionContent, appendVisualSection, projectVisualResume, updateVisualField } from './visual-projection'

describe('independent review regressions', () => {
  it('preserves a space typed after a name before the next character arrives', () => {
    const original = projectVisualResume(FIRST_USE_RESUME_TEMPLATE).fields.find(field => field.label === 'Name')!
    const afterSpace = updateVisualField(FIRST_USE_RESUME_TEMPLATE, original, original.value + ' ')
    const renderedAfterSpace = projectVisualResume(afterSpace).fields.find(field => field.label === 'Name')!
    expect(renderedAfterSpace.value).toBe('Alex Morgan ')
    const afterNextWord = updateVisualField(afterSpace, renderedAfterSpace, renderedAfterSpace.value + 'J')
    expect(projectVisualResume(afterNextWord).fields.find(field => field.label === 'Name')?.value).toBe('Alex Morgan J')
  })
  it('keeps the name projection on entering a newline', () => {
    const name = projectVisualResume(FIRST_USE_RESUME_TEMPLATE).fields.find(field => field.label === 'Name')!
    const afterEnter = updateVisualField(FIRST_USE_RESUME_TEMPLATE, name, 'Alex\nMorgan')
    expect(afterEnter).toContain('\\textbf{Alex\nMorgan}')
    expect(projectVisualResume(afterEnter).fields.find(field => field.label === 'Name')?.value).toBe('Alex\nMorgan')
  })
  it('preserves a plain paragraph after a whitespace-only replacement', () => {
    const description = projectVisualResume(FIRST_USE_RESUME_TEMPLATE).fields.find(field => field.label === 'Description')!
    const whitespace = updateVisualField(FIRST_USE_RESUME_TEMPLATE, description, ' ')
    expect(projectVisualResume(whitespace).fields.find(field => field.id === description.id)?.value).toBe(' ')
  })
  it('retains distinct visual groups for duplicate section titles', () => {
    const source = '\\begin{document}\n\\section{Experience}\nFirst role\n\\section{Experience}\nSecond role\n\\end{document}'
    const projection = projectVisualResume(source)
    expect(projection.fields.filter(field => field.kind === 'heading')).toHaveLength(2)
    expect(new Set(projection.fields.map(field => field.sectionId)).size).toBe(2)
    expect(projection.fields.filter(field => field.section === 'Experience' && field.kind !== 'heading').map(field => field.value)).toEqual(['First role', 'Second role'])
  })
  it('hides source code inside an unsupported listing environment', () => {
    const source = '\\begin{document}\n\\section{Projects}\n\\begin{lstlisting}\nconst secretCode = 123;\n\\end{lstlisting}\n\\end{document}'
    const projection = projectVisualResume(source)
    expect(projection.fields.some(field => field.value === 'const secretCode = 123;')).toBe(false)
  })

  it.each(['resumeSubheading', 'cventry'])('preserves neutral multiline input inside %s arguments without injecting line-break commands', (macro) => {
    const args = macro === 'cventry' ? '{2024}{Engineer}{Acme}{Remote}{}{Description}' : '{Engineer}{2024}{Acme}{Remote}'
    const source = `\\begin{document}\n\\section{Experience}\n\\${macro}${args}\n\\end{document}`
    const field = projectVisualResume(source).fields.find(candidate => candidate.label === 'Role or qualification')!
    const updated = updateVisualField(source, field, 'Senior\nEngineer')
    expect(updated).toBe(source.replace('{Engineer}', '{Senior\nEngineer}'))
    expect(updated).not.toContain('\\newline')
    expect(projectVisualResume(updated).fields.find(candidate => candidate.id === field.id)?.value).toBe('Senior\nEngineer')
  })

  it('retains blank lines and newline-only content as editable prose', () => {
    for (const text of ['First\n\nSecond', '\n', 'First\n']) {
      const field = projectVisualResume(FIRST_USE_RESUME_TEMPLATE).fields.find(candidate => candidate.label === 'Description')!
      const updated = updateVisualField(FIRST_USE_RESUME_TEMPLATE, field, text)
      expect(projectVisualResume(updated).fields.find(candidate => candidate.id === field.id)?.value).toBe(text)
      expect(updated).not.toContain('\\newline')
    }
  })

  it('projects Windows CRLF content like LF content without changing source coordinates', () => {
    const windows = FIRST_USE_RESUME_TEMPLATE.replace(/\n/g, '\r\n')
    const lf = projectVisualResume(FIRST_USE_RESUME_TEMPLATE)
    const crlf = projectVisualResume(windows)
    expect(crlf.fields.map(({ id, label, value, sectionId }) => ({ id, label, value, sectionId }))).toEqual(lf.fields.map(({ id, label, value, sectionId }) => ({ id, label, value, sectionId })))
    expect(crlf.fields.some(field => field.value.includes('\r'))).toBe(false)
    expect(crlf.fields.some(field => field.value === 'Customer Success Associate')).toBe(true)
    const name = crlf.fields.find(field => field.label === 'Name')!
    expect(updateVisualField(windows, name, 'Taylor Morgan')).toBe(windows.replace('Alex Morgan', 'Taylor Morgan'))
    const bullet = crlf.fields.find(field => field.kind === 'bullet')!
    expect(updateVisualField(windows, bullet, 'Updated achievement')).toBe(windows.slice(0, bullet.start) + 'Updated achievement' + windows.slice(bullet.end))
    expect(windows.slice(bullet.end, bullet.end + 2)).toBe('\r\n')
  })

  it('normalizes CRLF within a merged paragraph and a multiline macro value only in the visual text', () => {
    const source = '\\begin{document}\r\n\\section{Profile}\r\nFirst line\r\nSecond line\r\n\\resumeSubheading{Senior\r\nEngineer}{2024}{Acme}{Remote}\r\n\\end{document}'
    const projection = projectVisualResume(source)
    const paragraph = projection.fields.find(field => field.label === 'Description')!
    const role = projection.fields.find(field => field.label === 'Role or qualification')!
    expect(paragraph.value).toBe('First line\nSecond line')
    expect(role.value).toBe('Senior\nEngineer')
    expect(updateVisualField(source, paragraph, 'Updated prose')).toBe(source.replace('First line\r\nSecond line', 'Updated prose'))
  })

  it.each(['lstlisting', 'minted', 'verbatim', 'Verbatim', 'customlayout'])('preserves an unsupported %s block exactly when surrounding text changes', (environment) => {
    const hidden = `\\begin{${environment}}\n\\section{Hidden code heading}\nconst secretCode = 123;\n\\end{${environment}}`
    const source = `\\begin{document}\n\\section{Projects}\nBefore\n${hidden}\nAfter\n\\end{document}`
    const projection = projectVisualResume(source)
    expect(projection.fields.map(field => field.value)).toEqual(['Projects', 'Before', 'After'])
    let changed = source
    for (const text of ['Before', 'After']) {
      const field = projectVisualResume(changed).fields.find(candidate => candidate.value === text)!
      changed = updateVisualField(changed, field, `Updated ${text}`)
    }
    expect(changed).toBe(source.replace('\nBefore\n', '\nUpdated Before\n').replace('\nAfter\n', '\nUpdated After\n'))
    expect(changed).toContain(hidden)
  })

  it('inserts sections after preserved listings containing a literal document-end command', () => {
    const listing = '\\begin{lstlisting}\n\\end{document}\n\\end{lstlisting}'
    const source = `\\begin{document}\n\\section{Projects}\nReadable content\n${listing}\nAfter listing\n\\end{document}`
    const updated = appendVisualSection(source)
    const realEnd = source.lastIndexOf('\\end{document}')
    expect(updated.slice(0, realEnd)).toBe(source.slice(0, realEnd))
    expect(updated).toContain(listing)
    expect(updated.indexOf('\\section*{Additional experience}')).toBeGreaterThan(updated.indexOf('\\end{lstlisting}'))
    expect(projectVisualResume(updated).fields.some(field => field.value === 'Additional experience')).toBe(true)
  })

  it('does not insert achievements into a literal itemize example inside a preserved listing', () => {
    const listing = '\\begin{lstlisting}\n\\begin{itemize}\n\\item Example code\n\\end{itemize}\n\\end{lstlisting}'
    const source = `\\begin{document}\n\\section{Projects}\nReadable content\n${listing}\n\\end{document}`
    const heading = projectVisualResume(source).fields.find(field => field.kind === 'heading')!
    const updated = addVisualSectionContent(source, heading)
    expect(updated.kind).toBe('paragraph')
    expect(updated.source).toContain(listing)
    expect(updated.source).toBe(source.replace('\n\\end{document}', '\n\nDescribe your experience here.\n\n\\end{document}'))
  })
})
