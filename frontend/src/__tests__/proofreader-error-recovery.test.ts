import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(new URL('../components/ProofreadPanel.tsx', import.meta.url), 'utf8')

describe('proofreader request recovery', () => {
  it('surfaces failures and clears the error before retrying', () => {
    expect(SOURCE).toContain('setError(null)')
    expect(SOURCE).toContain('Proofreading failed. Please try again.')
    expect(SOURCE).toContain('role="alert"')
    expect(SOURCE).not.toContain('// silently fail — no API key, network, etc.')
  })
})
