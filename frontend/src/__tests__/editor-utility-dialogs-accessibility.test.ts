import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('editor utility feedback and dialog semantics', () => {
  it('invalidates in-flight detection when utility dialogs close or reopen', () => {
    for (const file of ['../components/ContactFormatterPanel.tsx', '../components/DateStandardizerPanel.tsx']) {
      const panel = source(file)
      expect(panel).toContain('const requestIdRef = useRef(0)')
      expect(panel).toContain('requestIdRef.current += 1')
      expect(panel).toContain('if (requestId !== requestIdRef.current) return')
      expect(panel).toContain('if (requestId === requestIdRef.current) setLoading(false)')
    }

    const datePanel = source('../components/DateStandardizerPanel.tsx')
    expect(datePanel).toMatch(
      /const handleFormatChange[\s\S]*requestIdRef\.current \+= 1[\s\S]*setLoading\(false\)/,
    )
  })

  it('exposes utility dialogs as modal dialogs with focus containment', () => {
    for (const file of ['../components/ContactFormatterPanel.tsx', '../components/DateStandardizerPanel.tsx']) {
      const panel = source(file)
      expect(panel).toContain('role="dialog"')
      expect(panel).toContain('aria-modal="true"')
      expect(panel).toContain('event.key === \'Escape\'')
      expect(panel).toContain("event.key !== 'Tab'")
    }
  })

  it('gives shared loading and compiler controls an accessible state', () => {
    const spinner = source('../components/LoadingSpinner.tsx')
    expect(spinner).toContain('role="status"')
    expect(spinner).toContain('aria-label={label}')

    const selector = source('../components/CompilerSelector.tsx')
    expect(selector).toContain('aria-expanded={open}')
    expect(selector).toContain('aria-haspopup="menu"')
    expect(selector).toContain('role="menuitemradio"')
    expect(selector).toContain('aria-checked={option.id === current}')
  })
})
