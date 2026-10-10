import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const fixture = readFileSync(new URL('../../e2e/editor-compile-sync.spec.ts', import.meta.url), 'utf8')

describe('source/PDF synchronization fixture contract', () => {
  it('selects Source for the exact resume before navigation instead of relying on the product default', () => {
    const selection = fixture.indexOf("localStorage.setItem(`latexy_editor_mode_${resumeId}`, 'source')")
    expect(selection).toBeGreaterThan(fixture.indexOf('await page.addInitScript(resumeId =>'))
    expect(selection).toBeLessThan(fixture.indexOf('}, RESUME_ID)'))
    expect(selection).toBeLessThan(fixture.indexOf('await page.goto(`/workspace/${RESUME_ID}/edit`'))
    expect(fixture).toContain('__latexyMonacoEditor?.getValue())).toBe(SOURCE)')
  })

  it('provides exact read-only capability and absent-attachment responses', () => {
    expect(fixture).toContain("path === '/public/engine/capabilities' && route.request().method() === 'GET'")
    expect(fixture).toContain('route.fulfill({ json: { resume_engine_version: 1 } })')
    expect(fixture).toContain("path === `/resumes/${RESUME_ID}/engine/import` && route.request().method() === 'GET'")
    expect(fixture).toContain("status: 404, json: { detail: 'No original PDF for this source fixture' }")
  })

  it('retains unknown-request rejection and real source, PDF and runtime-error assertions', () => {
    expect(fixture).toContain('unknown.push(`${route.request().method()} ${path}`)')
    expect(fixture).toContain('return route.abort()')
    expect(fixture).toContain('errors.push(error.message)')
    expect(fixture).toContain('expect(fixture.unknown).toEqual([])')
    expect(fixture).toContain('expect(fixture.errors).toEqual([])')
    expect(fixture).toContain("page.locator('.react-pdf__Page__canvas').first()).toBeVisible()")
  })
})
