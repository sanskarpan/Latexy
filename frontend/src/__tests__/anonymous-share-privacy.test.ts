import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const page = readFileSync(
  new URL('../app/r/[token]/page.tsx', import.meta.url),
  'utf8',
)

describe('anonymous share privacy', () => {
  it('does not render an iframe while the redacted PDF is processing', () => {
    expect(page).toContain('data.anonymous_processing || !data.pdf_url')
    expect(page).toContain('The original PDF is never shown')
  })

  it('offers the server-provided accessible text alternative', () => {
    expect(page).toContain("setView('text')")
    expect(page).toContain('data.accessible_text')
    expect(page).toContain('Accessible text')
  })

  it('labels a ready redacted PDF as an anonymous review copy', () => {
    expect(page).toContain('data.is_anonymous')
    expect(page).toContain('Anonymous review copy')
    expect(page).toContain('detected personal identifiers have been redacted')
  })
})
