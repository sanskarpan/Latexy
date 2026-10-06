import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(new URL('../components/DiffViewerModal.tsx', import.meta.url), 'utf8')

describe('DiffViewerModal keyboard lifecycle', () => {
  it('attaches Escape handling before the visible modal is painted', () => {
    expect(SOURCE).toContain('useLayoutEffect(() => {')
    expect(SOURCE).toContain("if (e.key === 'Escape')")
    expect(SOURCE).toContain("window.addEventListener('keydown', handler)")
  })
})
