import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../app/try/page.tsx', import.meta.url), 'utf8')

describe('/try mobile toolbar contract', () => {
  it('compacts the compile/export controls and hides only secondary toggles below sm', () => {
    expect(source).toContain('aria-label="Recompile"')
    expect(source).toContain('className="hidden sm:inline">{isProcessing || isSubmitting ? \'Compiling…\' : \'Recompile\'}</span>')
    expect(source).toContain('className="hidden sm:inline-flex"')
    expect(source).toContain('className="shrink-0 [&>button]:px-2 [&>button]:py-1.5 [&>button]:text-xs sm:[&>button]:px-4')
  })
})
