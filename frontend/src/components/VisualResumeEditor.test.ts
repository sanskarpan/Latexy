import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import VisualResumeEditor from './VisualResumeEditor'
import { FIRST_USE_RESUME_TEMPLATE } from '@/lib/first-use-resume'

describe('visual editor source isolation', () => {
  it('renders every section while excluding unrecognized source content', () => {
    const source = FIRST_USE_RESUME_TEMPLATE.replace('\\end{document}', '\\customlayout{DO_NOT_SHOW_984}\n\\end{document}')
    const markup = renderToStaticMarkup(createElement(VisualResumeEditor, { value: source, onChange: () => {} }))
    for (const section of ['Personal details', 'Profile', 'Experience', 'Education', 'Skills']) expect(markup).toContain(`aria-label="${section}"`)
    expect(markup).toContain('Alex Morgan')
    expect(markup).toContain('Customer communication')
    expect(markup).not.toContain('DO_NOT_SHOW_984')
    expect(markup).not.toMatch(/\\(?:customlayout|textbf|section|begin|usepackage)/)
  })

  it('shows the full read-only review without navigation or editing actions', () => {
    const markup = renderToStaticMarkup(createElement(VisualResumeEditor, { value: FIRST_USE_RESUME_TEMPLATE, onChange: () => {}, readOnly: true }))
    expect(markup).toContain('readonly=""')
    expect(markup).toContain('Customer communication')
    expect(markup).toContain('Example University')
    expect(markup).not.toContain('Add a section')
    expect(markup).not.toContain('Resume sections')
    expect(markup).not.toContain('Click any text to edit')
  })
})
