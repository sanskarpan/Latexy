import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../app/try/page.tsx', import.meta.url), 'utf8')

describe('/try mobile toolbar contract', () => {
  it('compacts the compile/export controls and hides only secondary toggles below sm', () => {
    expect(source).toContain('aria-label="Update PDF preview"')
    expect(source).toContain('className="hidden sm:inline">{isProcessing || isSubmitting ? \'Updating…\' : editorMode === \'source\' ? \'Recompile\' : \'Update PDF\'}</span>')
    expect(source).toContain('className="hidden sm:inline-flex"')
    expect(source).toContain('className="shrink-0 [&>button]:px-2 [&>button]:py-1.5 [&>button]:text-xs sm:[&>button]:px-4 sm:[&>button]:py-2 sm:[&>button]:text-sm"')
  })

  it('checks full-stack controls by their shipped accessible names, including the denied Auto control', () => {
    const smoke = readFileSync(new URL('../../e2e/full-stack-smoke.spec.ts', import.meta.url), 'utf8')
    const capabilities = readFileSync(new URL('../../e2e/capability-fullstack.spec.ts', import.meta.url), 'utf8')
    for (const label of ['Update PDF preview', 'Automatically update the PDF after edits']) {
      expect(source).toContain(`aria-label="${label}"`)
      expect(capabilities).toContain(`name: '${label}'`)
    }
    expect(smoke).toContain("getByRole('button', { name: 'Update PDF preview', exact: true })).toBeVisible()")
    expect(smoke).not.toContain('name: /recompile/i')
    expect(capabilities).toContain("getByRole('button', { name: 'Automatically update the PDF after edits', exact: true })).toHaveCount(0)")
    expect(capabilities).not.toContain('Auto-compile on change')
    expect(capabilities).toContain("locator('[aria-label=\"Source and PDF synchronization\"]')).toHaveCount(0)")
    expect(capabilities).toContain('expect(guestDenied.status()).toBe(403)')
  })
})
