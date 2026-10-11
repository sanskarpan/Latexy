import { createHash } from 'node:crypto'
import type { Page, Route } from '@playwright/test'
import { fulfillQualityJson, qualityCorsHeaders, QUALITY_FEATURES } from './mock-api'

/** Preflight must not read a body, mutate fixture state, or count as an API call. */
export async function mockEngineRoute(page: Page, url: Parameters<Page['route']>[0], handler: (route: Route) => Promise<void> | void) {
  await page.route(url, route => {
    if (route.request().method() === 'OPTIONS') return fulfillQualityJson(route, null)
    return handler(route)
  })
}

/** JSON and binary artifacts obey the same credentialed cross-origin contract. */
export function fulfillEngineResponse(route: Route, response: NonNullable<Parameters<Route['fulfill']>[0]>) {
  if (route.request().method() === 'OPTIONS') return fulfillQualityJson(route, null)
  return route.fulfill({ ...response, headers: { ...qualityCorsHeaders(route), ...(response.contentType ? { 'content-type': response.contentType } : {}), ...response.headers } })
}

/** Mock ancillary API calls by path, independent of the isolated server's port. */
export async function mockEngineAncillaryApi(page: Page, ownerId = 'contract-owner', features: Record<string, boolean> = {}) {
  const effectiveFeatures = { ...QUALITY_FEATURES }
  for (const [key, allowed] of Object.entries(features)) {
    if (!Object.prototype.hasOwnProperty.call(QUALITY_FEATURES, key)) throw new Error(`Unknown quality capability: ${key}`)
    effectiveFeatures[key] = allowed
  }
  await mockEngineRoute(page, url => [
    '/me', '/config/entitlements', '/config/feature-flags', '/public/engine/capabilities',
    '/tenants/resolve-host', '/ats/quick-score', '/macros', '/github/status',
    '/dropbox/status', '/subscription/current', '/ws/ticket', '/telemetry/frontend',
    '/analytics/track/compilation', '/analytics/track/feature-usage',
  ].includes(url.pathname) || url.pathname === '/templates' || url.pathname.startsWith('/templates/')
    || /^\/resumes\/[^/]+\/academic-cv-report$/.test(url.pathname)
    || /^\/download\/[^/]+\/preview\/[^/]+\/synctex$/.test(url.pathname), route => {
    // Do not intercept a Next document or an RSC navigation to /templates.
    if (!['fetch', 'xhr', 'ping'].includes(route.request().resourceType())
      || route.request().headers().rsc === '1') return route.fallback()
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/synctex')) return fulfillEngineResponse(route, { status: 404, json: { detail: 'Optional SyncTeX is unavailable in this fixture' } })
    if (path === '/telemetry/frontend' || path.startsWith('/analytics/track/')) return fulfillEngineResponse(route, { status: 204 })
    const json = path === '/config/entitlements' ? { features: effectiveFeatures }
      : path === '/public/engine/capabilities' ? { resume_engine_version: 1 }
      : path === '/me' ? { id: ownerId, preferences: { has_onboarded: true } }
        : path === '/tenants/resolve-host' ? { tenant: null }
          : path === '/ats/quick-score' ? { score: 80, grade: 'B', sections_found: [], missing_sections: [], keyword_match_percent: null }
            : path === '/github/status' ? { connected: false, username: null, public_import: false, private_sync: false }
              : path === '/dropbox/status' ? { connected: false, display_name: null, account_id: null }
                : path === '/subscription/current' ? { userId: ownerId, planId: 'free', planName: 'Free', status: 'active',
                  features: { compilations: 5, optimizations: 0, historyRetention: 0, prioritySupport: false, apiAccess: false } }
                  : path === '/ws/ticket' ? { ticket: 'contract-ticket' }
                    : path.endsWith('/academic-cv-report') ? { is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }
                      : path === '/macros' || path.startsWith('/templates') ? [] : {}
    return fulfillEngineResponse(route, { json })
  })
}

/** Public-page layout tests need a valid read-only projection, not a live engine. */
export async function mockPublicEngineDocument(page: Page) {
  await mockEngineRoute(page, '**/public/engine/document', route => {
    const { latex_content } = route.request().postDataJSON() as { latex_content: string }
    return fulfillEngineResponse(route, { json: {
      latex_content,
      document: {
        document_id: 'guest', source_mode: 'imported', content_revision: 1,
        source_sha256: createHash('sha256').update(latex_content).digest('hex'),
        structured_version: null, template_id: null, nodes: [], opaque_blocks: [], containers: [],
      },
    } })
  })
}

export function readMonacoSource(page: Page) {
  return page.evaluate(() => (window as typeof window & {
    __latexyMonacoEditor?: { getValue(): string }
  }).__latexyMonacoEditor?.getValue())
}

/** Observe the Copy button without removing Monaco's native WebKit write API. */
export async function captureClipboardText(page: Page) {
  await page.evaluate(() => Object.defineProperty(navigator.clipboard, 'writeText', {
    configurable: true,
    value: async (text: string) => {
      ;(window as typeof window & { copiedLatex?: string }).copiedLatex = text
    },
  }))
}
