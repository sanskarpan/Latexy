import { expect, test as base } from '@playwright/test'
import { installMockWorkboxRegistration } from '../helpers/mock-workbox-registration'

// Only synthetic quality contracts use this fixture. Keep production PWA
// generation and e2e/pwa-production.spec.ts on the real service-worker path.
export const test = base.extend({
  context: async ({ context }, runTest) => {
    await installMockWorkboxRegistration(context)
    await runTest(context)
  },
})

export { expect }
export type { Page, Request, WebSocketRoute } from '@playwright/test'
