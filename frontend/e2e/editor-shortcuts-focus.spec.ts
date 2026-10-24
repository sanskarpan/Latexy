import { createHash } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'
import { installMockWorkboxRegistration } from './helpers/mock-workbox-registration'
import { fulfillEngineResponse, mockEngineAncillaryApi, mockEngineRoute, readMonacoSource } from './quality/engine-fixtures'

const ID = 'f9a1126d-3b32-46ae-831a-e37359783999'
const OWNER = 'shortcuts-focus-owner'
const SOURCE = '\\documentclass{article}\n\\begin{document}Keyboard shortcuts fixture.\\end{document}'

test.use({ serviceWorkers: 'block' })

async function readSource(page: Page) {
  const mobile = page.locator('.cm-content[contenteditable="true"]')
  return await mobile.count() ? mobile.innerText() : readMonacoSource(page)
}

async function sourceHasFocus(page: Page) {
  const mobile = page.locator('.cm-content[contenteditable="true"]')
  return await mobile.count()
    ? mobile.evaluate(node => node === document.activeElement)
    : page.evaluate(() => (window as any).__latexyMonacoEditor?.hasTextFocus() === true)
}

async function openSavedEditor(page: Page) {
  await installMockWorkboxRegistration(page)
  await page.addInitScript(id => {
    localStorage.setItem(`latexy_editor_mode_${id}`, 'source')
    localStorage.setItem('latexy_auto_compile', 'false')
  }, ID)
  const unknown: string[] = []
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const appOrigin = new URL(test.info().project.use.baseURL!).origin
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.origin === appOrigin && !url.pathname.startsWith('/api/') && ['GET', 'HEAD'].includes(route.request().method())) return route.continue()
    unknown.push(`${route.request().method()} ${url.pathname}`)
    return route.abort()
  })
  await mockEngineAncillaryApi(page, OWNER, { c04: true, c05: false, c06: false })
  await mockEngineRoute(page, url => url.pathname === '/api/auth/get-session', route => fulfillEngineResponse(route, {
    json: { session: { token: 'shortcuts-synthetic-session' }, user: { id: OWNER, email: 'shortcuts@example.invalid', name: 'Shortcuts owner', role: 'user' } },
  }))
  await mockEngineRoute(page, '**/me', route => fulfillEngineResponse(route, {
    json: { id: OWNER, role: 'user', preferences: { has_onboarded: true } },
  }))
  await mockEngineRoute(page, '**/public/engine/capabilities', route => fulfillEngineResponse(route, {
    status: 404, json: { detail: 'The bounded shortcut fixture uses the saved source editor' },
  }))
  await mockEngineRoute(page, `**/resumes/${ID}`, route => {
    expect(route.request().method()).toBe('GET')
    return fulfillEngineResponse(route, { json: {
      id: ID, user_id: OWNER, access_role: 'owner', title: 'Shortcuts focus fixture', latex_content: SOURCE,
      content_revision: 1, document_type: 'resume', metadata: { compiler: 'lualatex' },
      created_at: '2026-10-23T00:00:00Z', updated_at: '2026-10-23T00:00:00Z',
    } })
  })
  await mockEngineRoute(page, `**/resumes/${ID}/latest-accepted-artifact`, route => fulfillEngineResponse(route, {
    json: { artifact: null, source_sha256: createHash('sha256').update(SOURCE).digest('hex'), content_revision: 1 },
  }))
  await mockEngineRoute(page, url => /\/(checkpoints|comments|collaborators|suggestions)$/.test(url.pathname), route => fulfillEngineResponse(route, { json: [] }))
  await page.routeWebSocket('**/ws/**', socket => socket.close())
  await page.goto(`/workspace/${ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect.poll(() => readSource(page)).toBe(SOURCE)
  const mobile = page.locator('.cm-content[contenteditable="true"]')
  if (await mobile.count()) await mobile.focus()
  else await page.evaluate(() => (window as any).__latexyMonacoEditor.focus())
  await expect.poll(() => sourceHasFocus(page)).toBe(true)
  return { unknown, errors }
}

async function openShortcuts(page: Page) {
  await page.keyboard.press('Control+Shift+Slash')
  const dialog = page.getByRole('dialog', { name: 'Keyboard Shortcuts', exact: true })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: 'Search keyboard shortcuts', exact: true })).toBeFocused()
  return dialog
}

async function expectEditorRestored(page: Page) {
  await expect(page.getByRole('dialog', { name: 'Keyboard Shortcuts', exact: true })).toHaveCount(0)
  await expect.poll(() => sourceHasFocus(page)).toBe(true)
  expect(await readSource(page)).toBe(SOURCE)
}

test('C04 keyboard shortcut dialog contains focus and restores the saved source opener', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  const fixture = await openSavedEditor(page)
  const dialog = await openShortcuts(page)
  // Traverse the actual native focus order; never force focus inside the modal.
  for (const key of ['Tab', 'Shift+Tab'] as const) {
    for (let step = 0; step < 6; step += 1) {
      await page.keyboard.press(key)
      await expect.poll(() => dialog.evaluate(node => node.contains(document.activeElement))).toBe(true)
    }
  }
  await page.keyboard.press('Escape')
  await expectEditorRestored(page)
  const reopened = await openShortcuts(page)
  await page.keyboard.press('Shift+Tab')
  await expect(reopened.getByRole('button', { name: 'Close keyboard shortcuts', exact: true })).toBeFocused()
  await page.keyboard.press('Enter')
  await expectEditorRestored(page)
  expect(fixture.unknown).toEqual([])
  expect(fixture.errors).toEqual([])
})

test('C04 shortcut dialog remains reachable and keyboard scrollable at 320 CSS pixels', async ({ page }) => {
  // This is narrow CSS-viewport acceptance, not browser-chrome zoom or a reader.
  await page.setViewportSize({ width: 320, height: 568 })
  const fixture = await openSavedEditor(page)
  const dialog = await openShortcuts(page)
  const bounds = await dialog.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(568)
  const close = dialog.getByRole('button', { name: 'Close keyboard shortcuts', exact: true })
  const closeBounds = await close.boundingBox()
  expect(closeBounds).not.toBeNull()
  expect(closeBounds!.y).toBeGreaterThanOrEqual(0)
  const footerBounds = await dialog.getByText('Press Esc to close', { exact: true }).boundingBox()
  expect(footerBounds).not.toBeNull()
  expect(footerBounds!.y + footerBounds!.height).toBeLessThanOrEqual(568)
  const list = dialog.getByRole('region', { name: 'Keyboard shortcuts list', exact: true })
  await page.keyboard.press('Tab')
  await expect(list).toBeFocused()
  const start = await list.evaluate(node => node.scrollTop)
  await page.keyboard.press('PageDown')
  await expect.poll(() => list.evaluate(node => node.scrollTop)).toBeGreaterThan(start)
  await page.keyboard.press('Escape')
  await expectEditorRestored(page)
  expect(fixture.unknown).toEqual([])
  expect(fixture.errors).toEqual([])
})
