import type { BrowserContext, Page } from '@playwright/test'

// Production-asset synthetic QA only; real service-worker lifecycle is outside
// these owner fixtures. With serviceWorkers:block, register() resolves
// undefined while the production Workbox bundle expects a registration shape.
export async function installMockWorkboxRegistration(target: Page | BrowserContext) {
  await target.addInitScript(() => {
    const registration = {
      installing: null,
      waiting: null,
      active: null,
      scope: ['http:', 'https:'].includes(window.location.protocol)
        ? new URL('/', window.location.href).href : window.location.href,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      update: async () => registration,
      unregister: async () => true,
    }
    const serviceWorker = {
      controller: null,
      register: async () => registration,
      getRegistration: async () => registration,
      getRegistrations: async () => [registration],
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: serviceWorker,
    })
  })
}
