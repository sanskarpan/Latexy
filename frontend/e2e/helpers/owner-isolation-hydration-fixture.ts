import { test as base, type Page, type Response, type TestInfo } from '@playwright/test'
import { installLegacySettingsHydrationDiagnostics, parseHydrationDiagnosticBundleVariant, type MainDocumentObservation } from './legacy-settings-hydration-diagnostics'

export type OwnerIsolationHydration = {
  requireDocuments: (minimum: 1 | 2) => void
  expectSyntheticOpenerOnly: () => void
}

// This classification reads response metadata only. SPA history changes, API
// traffic, redirects and subframes cannot stand in for a hydrated document.
export function mainDocumentKind(page: Page, response: Response, baseURL: URL): 'app' | 'synthetic-opener' | null {
  const request = response.request()
  if (!request.isNavigationRequest() || request.resourceType() !== 'document' || request.frame() !== page.mainFrame()
    || response.status() < 200 || response.status() >= 300
    || !/^text\/html(?:;|$)/i.test(response.headers()['content-type'] ?? '')) return null
  const url = new URL(response.url())
  if (url.origin !== baseURL.origin) return null
  if (url.pathname === '/__legacy-callback-test-opener') return 'synthetic-opener'
  // These are the only application entry documents in these two test families.
  return url.pathname === '/settings' || url.pathname === '/workspace' ? 'app' : null
}

export async function runOwnerIsolationHydrationFixture(
  page: Page, baseURL: URL, testInfo: TestInfo,
  runTestBody: (control: OwnerIsolationHydration) => Promise<void>,
) {
  const metadata = testInfo.project.metadata
  const variant = Object.prototype.hasOwnProperty.call(metadata, 'hydrationDiagnosticBundle')
    ? parseHydrationDiagnosticBundleVariant(metadata.hydrationDiagnosticBundle) : 'canonical'
  // Ordinary pnpm test uses development assets. This exact production-byte pin
  // is mandatory only in the explicitly selected production acceptance run.
  if (process.env.PLAYWRIGHT_SERVER_MODE !== 'production') {
    await runTestBody({ requireDocuments: () => {}, expectSyntheticOpenerOnly: () => {} })
    return
  }
  const observation: MainDocumentObservation = {
    expectedDocuments: 1, successfulAppDocuments: 0,
    successfulSyntheticOpeners: 0, syntheticOpenerOnly: false,
  }
  const onResponse = (response: Response) => {
    const kind = mainDocumentKind(page, response, baseURL)
    if (kind === 'app') observation.successfulAppDocuments = Math.min(33, observation.successfulAppDocuments + 1)
    if (kind === 'synthetic-opener') observation.successfulSyntheticOpeners = Math.min(33, observation.successfulSyntheticOpeners + 1)
  }
  page.on('response', onResponse)
  const diagnostics = await installLegacySettingsHydrationDiagnostics(page, baseURL, variant)
  const control: OwnerIsolationHydration = {
    requireDocuments(minimum) {
      if (minimum !== 1 && minimum !== 2) throw new Error('Invalid main-document hydration requirement')
      observation.expectedDocuments = minimum
      observation.syntheticOpenerOnly = false
    },
    expectSyntheticOpenerOnly() {
      observation.expectedDocuments = 0
      observation.syntheticOpenerOnly = true
    },
  }
  let originalFailure = false
  try {
    await runTestBody(control)
    // Playwright use() completes during teardown even when the test failed.
    // Preserve failed/timed-out/interrupted/skipped test outcomes unchanged.
    if (testInfo.status !== 'passed') return
    if (observation.syntheticOpenerOnly) {
      if (observation.successfulAppDocuments !== 0 || observation.successfulSyntheticOpeners === 0) {
        throw new Error('Synthetic-opener-only hydration scope could not be verified')
      }
    } else {
      if (observation.successfulAppDocuments < observation.expectedDocuments) {
        throw new Error('Required main app documents could not be observed')
      }
      observation.expectedDocuments = Math.max(observation.expectedDocuments, observation.successfulAppDocuments)
      await diagnostics.verifyReady(observation.expectedDocuments)
    }
  } catch (error) {
    originalFailure = true
    throw error
  } finally {
    page.off('response', onResponse)
    await diagnostics.finish(testInfo, originalFailure || testInfo.status !== 'passed', observation)
  }
}

// One automatic observer per primary page, before beforeEach/test navigation.
// Popups retain their existing page-error/behavior assertions without pretending
// an asynchronous popup attachment observed their initial React hydration.
export const test = base.extend<{ ownerIsolationHydration: OwnerIsolationHydration }>({
  ownerIsolationHydration: [async ({ page, baseURL }, use, testInfo) => {
    await runOwnerIsolationHydrationFixture(page, new URL(baseURL ?? 'about:blank'), testInfo, use)
  }, { auto: true }],
})
