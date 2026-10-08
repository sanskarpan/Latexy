import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const landingSource = readFileSync(
  fileURLToPath(new URL('../app/page.tsx', import.meta.url)),
  'utf8',
)
const entrySource = readFileSync(
  fileURLToPath(new URL('../components/marketing/MarketingSections.tsx', import.meta.url)),
  'utf8',
)

describe('homepage compile claims', () => {
  it('describes previews without promising an uncertified end-to-end duration', () => {
    expect(landingSource).toContain('Professional PDF output')
    expect(landingSource).not.toMatch(/sub[\s-]?second/i)
    expect(landingSource).not.toMatch(/compiled\s+\d+(?:\.\d+)?\s*(?:ms|s)\b/i)
  })

  it('retains the existing entry point and public ownership verification', () => {
    expect(landingSource).toContain('<MarketingCTA />')
    expect(entrySource).toContain("label = 'Build my résumé'")
    expect(entrySource).toContain("href = '/try?mode=visual'")
    expect(landingSource).toContain("google: '-JuXguMIM_kaznXdcKY8ygd7x6Iuhndu1xvV3_arsHs'")
  })
})
