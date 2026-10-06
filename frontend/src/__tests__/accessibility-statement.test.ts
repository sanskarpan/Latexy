import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const statement = readFileSync(
  new URL('../app/accessibility/page.tsx', import.meta.url),
  'utf8',
)
const footer = readFileSync(
  new URL('../components/marketing/MarketingFooter.tsx', import.meta.url),
  'utf8',
)

describe('accessibility statement', () => {
  it('publishes an honest status and names current limitations', () => {
    expect(statement).toContain('not a claim of WCAG conformance')
    expect(statement).toContain('Generated PDFs are not yet guaranteed to be tagged PDF/UA')
    expect(statement).toContain('do not yet claim verified')
  })

  it('provides a prioritized support path and is linked publicly', () => {
    expect(statement).toContain('Accessibility%20support')
    expect(statement).toContain('within two')
    expect(footer).toContain('href="/accessibility"')
  })
})
