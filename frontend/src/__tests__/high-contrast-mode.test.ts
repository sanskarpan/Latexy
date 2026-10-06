import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (relativePath: string) =>
  fs.readFileSync(path.join(process.cwd(), relativePath), 'utf8')

describe('high contrast mode', () => {
  it('bootstraps from a dedicated cookie or the operating-system preference', () => {
    const layout = read('src/app/layout.tsx')
    expect(layout).toContain('latexy-contrast=(normal|high)')
    expect(layout).toContain("prefers-contrast: more")
    expect(layout).toContain("setAttribute('data-contrast',contrast)")
  })

  it('provides explicit light and dark enhanced-contrast token sets', () => {
    const tokens = read('src/app/design-tokens.css')
    expect(tokens).toContain(':root[data-contrast="high"][data-mode="light"]')
    expect(tokens).toContain(':root[data-contrast="high"][data-mode="dark"]')
  })

  it('keeps the control reachable in standard and fullscreen headers', () => {
    const files = [
      'src/components/GlobalHeader.tsx',
      'src/app/try/page.tsx',
      'src/app/workspace/[resumeId]/edit/page.tsx',
      'src/app/workspace/[resumeId]/optimize/page.tsx',
      'src/app/workspace/[resumeId]/cover-letter/page.tsx',
    ]
    for (const file of files) expect(read(file), file).toContain('<ContrastToggle />')
  })

  it('does not accept theme-control clicks before hydration attaches handlers', () => {
    const provider = read('src/components/theme/ThemeProvider.tsx')
    const modeToggle = read('src/components/theme/ModeToggle.tsx')
    const contrastToggle = read('src/components/theme/ContrastToggle.tsx')

    expect(provider).toContain('const [ready, setReady] = useState(false)')
    expect(provider).toContain('setReady(true)')
    expect(modeToggle).toContain('disabled={!ready}')
    expect(contrastToggle).toContain('disabled={!ready}')
  })
})
