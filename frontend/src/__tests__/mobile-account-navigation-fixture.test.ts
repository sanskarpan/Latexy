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
    expect(fixture).toContain('expect(diagnostics.pageErrors).toEqual([])')
    expect(fixture).toContain('expect(diagnostics.unmockedApiRequests).toEqual([])')
    expect(fixture).toContain('expect([...diagnostics.unexpectedAuthRequests.values()]).toEqual([])')
  })
})
