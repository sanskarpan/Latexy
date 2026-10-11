import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../app/try/page.tsx', import.meta.url), 'utf8')

describe('/try mobile toolbar contract', () => {
  it('compacts the compile/export controls and hides only secondary toggles below sm', () => {
    expect(source).toContain('aria-label="Update PDF preview"')
    expect(source).toContain('className="hidden sm:inline">')
    expect(source).toContain("isProcessing || isSubmitting ? 'Preparing…' : 'Update preview'")
    expect(source).toContain('bg-accent px-2 py-1.5 font-ui text-xs')
    expect(source).toContain('sm:px-3.5')
    expect(source).toContain('className={`hidden select-none items-center gap-1.5 rounded-[var(--radius-md)] border px-2 py-1.5 font-ui text-[12px] transition sm:flex')
    expect(source).toContain('className="hidden items-center gap-1.5 rounded-[var(--radius-pill)] border border-line bg-surface-2 px-2.5 py-1 font-ui text-[12px] text-fg-2 transition hover:border-accent sm:flex"')
    expect(source).toContain('className="hidden sm:inline-flex"')
    expect(source).toContain('className="shrink-0 [&>button]:px-2 [&>button]:py-1.5 [&>button]:text-xs sm:[&>button]:px-4 sm:[&>button]:py-2 sm:[&>button]:text-sm"')
  })
})
