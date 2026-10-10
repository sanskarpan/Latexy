import { createHash } from 'node:crypto'
import type { Page } from '@playwright/test'

/** Mock ancillary API calls by path, independent of the isolated server's port. */
export async function mockEngineAncillaryApi(page: Page, ownerId = 'contract-owner') {
  await page.route(url => [
    '/me', '/config/entitlements', '/config/feature-flags',
    '/tenants/resolve-host', '/ats/quick-score', '/macros',
  ].includes(url.pathname) || url.pathname === '/templates' || url.pathname.startsWith('/templates/'), route => {
    // Do not intercept a Next document or an RSC navigation to /templates.
    if (!['fetch', 'xhr'].includes(route.request().resourceType())
      || route.request().headers().rsc === '1') return route.fallback()
    const path = new URL(route.request().url()).pathname
    const json = path === '/me' ? { id: ownerId, preferences: { has_onboarded: true } }
      : path === '/tenants/resolve-host' ? { tenant: null }
        : path === '/ats/quick-score' ? { score: 80, grade: 'B', sections_found: [], missing_sections: [], keyword_match_percent: null }
          : path === '/macros' || path.startsWith('/templates') ? [] : {}
    return route.fulfill({ json })
  })
}

/** Public-page layout tests need a valid read-only projection, not a live engine. */
export async function mockPublicEngineDocument(page: Page) {
  await page.route('**/public/engine/document', route => {
    const { latex_content } = route.request().postDataJSON() as { latex_content: string }
    return route.fulfill({ json: {
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
