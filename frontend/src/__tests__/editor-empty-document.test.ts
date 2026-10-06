import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(new URL('../components/LaTeXEditor.tsx', import.meta.url), 'utf8')

describe('empty LaTeX editor lifecycle', () => {
  it('keeps Monaco mounted so clearing the document preserves undo history', () => {
    expect(SOURCE).not.toContain('!value ? (')
    expect(SOURCE).toContain('<MonacoEditor')
    expect(SOURCE).toContain('{!value && (')
  })

  it('clears disposed editor references on unmount', () => {
    expect(SOURCE).toContain('editorRef.current = null')
    expect(SOURCE).toContain('monacoRef.current = null')
  })
})
