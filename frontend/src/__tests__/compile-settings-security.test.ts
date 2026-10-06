import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { ALLOWED_LATEXMK_FLAGS } from '@/lib/api-client'

describe('compile-settings security contract', () => {
  it('never offers shell escape as a compiler flag', () => {
    expect(ALLOWED_LATEXMK_FLAGS).not.toContain('--shell-escape')

    const modal = readFileSync(
      new URL('../components/CompileSettingsModal.tsx', import.meta.url),
      'utf8',
    )
    expect(modal).not.toContain("'--shell-escape':")
    expect(modal).toContain('arbitrary command execution is prohibited')
    expect(modal).not.toContain('TEXLIVE_VERSIONS')
    expect(modal).not.toContain('texlive_version: texliveVersion')
    expect(modal).toContain('Per-resume version pinning is not supported')
  })

  it('does not offer packages that require the prohibited flag', () => {
    const packages = readFileSync(
      new URL('../data/latex-packages.ts', import.meta.url),
      'utf8',
    )
    expect(packages).not.toContain("name: 'minted'")
  })
})
