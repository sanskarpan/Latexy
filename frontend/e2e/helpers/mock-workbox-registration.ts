import type { Page } from '@playwright/test'

// Production-asset synthetic QA only; real service-worker lifecycle is outside
// these owner fixtures. With serviceWorkers:block, register() resolves
// undefined while the production Workbox bundle expects a registration shape.
export async function installMockWorkboxRegistration(page: Page) {
  await page.addInitScript(() => {
    const registration = {
      installing: null,
      waiting: null,
      active: null,
      scope: new URL('/', window.location.href).href,
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
