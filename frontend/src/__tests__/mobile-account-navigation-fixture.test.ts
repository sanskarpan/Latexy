import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const fixture = readFileSync(new URL('../../e2e/quality/mobile-account-navigation.spec.ts', import.meta.url), 'utf8')
const signOutFlow = fixture.slice(
  fixture.indexOf("test('authenticated users can reach account controls"),
  fixture.indexOf("test('guests see login actions"),
)

describe('mobile account navigation fixture sequencing', () => {
  it('settles the first guest document before reloading and independently verifies persistence', () => {
    const steps = [
      'await expect.poll(() => fixture.getGuestSessionReads()).toBeGreaterThan(0)',
      'await waitForHeaderSession(page, fixture)',
      'await expectGuestAccountNavigation(page)',
      "await page.waitForLoadState('networkidle')",
      'const guestSessionReadsBeforeReload = fixture.getGuestSessionReads()',
      "await page.reload({ waitUntil: 'networkidle' })",
      'await expect.poll(() => fixture.getGuestSessionReads()).toBeGreaterThan(guestSessionReadsBeforeReload)',
      'await waitForHeaderSession(page, fixture)',
      'await expectGuestAccountNavigation(page)',
      'expect(signOutCalls).toBe(1)',
    ]
    let previous = -1
    for (const step of steps) {
      const position = signOutFlow.indexOf(step, previous + 1)
      expect(position, `Missing or out-of-order fixture step: ${step}`).toBeGreaterThan(previous)
      previous = position
    }
    expect(signOutFlow).not.toContain('waitForTimeout')
  })

  it('checks the real guest controls while retaining all runtime and request errors', () => {
    const guestAssertions = fixture.slice(
      fixture.indexOf('async function expectGuestAccountNavigation'),
      fixture.indexOf("test.describe('mobile account navigation'"),
    )
    expect(guestAssertions).toContain("getByRole('link', { name: 'Log In', exact: true })).toBeVisible()")
    expect(guestAssertions).toContain("getByRole('link', { name: 'Try Free', exact: true })).toBeVisible()")
    expect(guestAssertions).toContain("getByRole('button', { name: 'Sign Out', exact: true })).toHaveCount(0)")
    expect(fixture).toContain('pageErrors.push(error.message)')
    expect(fixture).toContain('pageErrors: diagnostics.pageErrors')
    expect(fixture).toContain('expect(classification.unclassified).toEqual([])')
    expect(fixture).toContain('expect(ledger?.runId).toBe(diagnostics.runId)')
    expect(fixture).toContain('expect(ledger?.overflow).toBe(false)')
    expect(fixture).toContain('expect(ledger?.documents.flatMap(doc => doc.windowErrors) ?? []).toEqual([])')
    expect(fixture).toContain('expect(diagnostics.unmockedApiRequests).toEqual([])')
    expect(fixture).toContain('expect([...diagnostics.unexpectedAuthRequests.values()]).toEqual([])')
  })

  it('arms provenance only for the deliberate sign-out click, without changing product navigation', () => {
    expect(signOutFlow).toContain('await fixture.beginSignOutNavigation()')
    expect(signOutFlow.indexOf('await fixture.beginSignOutNavigation()')).toBeLessThan(
      signOutFlow.indexOf("await page.getByRole('button', { name: 'Sign Out', exact: true }).click()"),
    )
    expect(fixture).toContain('postSucceededAt')
    expect(fixture).toContain('request.isNavigationRequest()')
    expect(fixture).toContain('request.frame() === page.mainFrame()')
    expect(fixture).not.toContain("trace: 'retain-on-failure'")
  })

  it('requires zero transient-menu prefetches and real click navigation', () => {
    const clickFlow = fixture.slice(
      fixture.indexOf("test('account links still navigate on click"),
      fixture.indexOf("test('guests with Studio disabled"),
    )
    expect(signOutFlow).toContain('expect(signOutDocument).not.toBeNull()')
    expect(signOutFlow).toContain('expect(signOutDocument?.fetches).toEqual([])')
    expect(clickFlow).toMatch(/page\.getByRole\('region', \{ name: 'Account', exact: true \}\)\s*\.getByRole\('link', \{ name: 'Terms', exact: true \}\)\.click\(\)/)
    expect(clickFlow).not.toContain("page.getByRole('link', { name: 'Terms'")
    expect(clickFlow).not.toMatch(/\.first\(|\.nth\(/)
    expect(clickFlow).toContain("getByRole('heading', { name: 'Terms of Service', level: 1 })).toBeVisible()")
    expect(clickFlow).toContain('expect(prefetches).toEqual([])')
  })
})
