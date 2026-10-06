import { describe, expect, it } from 'vitest'
import {
  applyCoverLetterSignature,
  hasCoverLetterSignature,
  removeCoverLetterSignature,
} from '@/lib/cover-letter-signature'

const SOURCE = '\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}'

describe('cover-letter signatures', () => {
  it('escapes a typed signature and replaces the previous signature', () => {
    const first = applyCoverLetterSignature(SOURCE, { mode: 'typed', name: 'Ada & Co.' })
    const second = applyCoverLetterSignature(first, { mode: 'typed', name: 'Grace_Hopper' })
    expect(first).toContain('Ada \\& Co.')
    expect(second).not.toContain('Ada')
    expect(second).toContain('Grace\\_Hopper')
    expect(second.match(/LATEXY_SIGNATURE_START/g)).toHaveLength(1)
  })

  it('wraps image data and removes all owned blocks reversibly', () => {
    const signed = applyCoverLetterSignature(SOURCE, {
      mode: 'image',
      name: 'Ada',
      dataUrl: `data:image/png;base64,${'A'.repeat(160)}`,
    })
    expect(hasCoverLetterSignature(signed)).toBe(true)
    expect(signed).toContain('\\usepackage{graphicx}')
    expect(signed.match(/LATEXY_SIGNATURE_DATA:/g)).toHaveLength(3)
    expect(removeCoverLetterSignature(signed).trim()).toBe(SOURCE)
  })

  it('rejects malformed image data and documents', () => {
    expect(() => applyCoverLetterSignature(SOURCE, { mode: 'image', name: '', dataUrl: 'https://example.com/a.png' })).toThrow()
    expect(() => applyCoverLetterSignature('not latex', { mode: 'typed', name: 'Ada' })).toThrow()
  })
})
