import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const PREVIEW_SOURCE = readFileSync(
  new URL('../components/TemplatePreviewModal.tsx', import.meta.url),
  'utf8',
)
const LIBRARY_SOURCE = readFileSync(
  new URL('../app/templates/page.tsx', import.meta.url),
  'utf8',
)

describe('template preview compiler contract', () => {
  it('matches the LuaLaTeX compiler used for newly created templates', () => {
    expect(PREVIEW_SOURCE).toContain('LaTeX (LuaLaTeX)')
    expect(PREVIEW_SOURCE).not.toContain('LaTeX (pdflatex)')
  })

  it('does not offer Europecv locales rejected by the compiler contract', () => {
    expect(LIBRARY_SOURCE).not.toContain("['lv', 'Latvian']")
    expect(LIBRARY_SOURCE).not.toContain("['sl', 'Slovenian']")
  })
})
