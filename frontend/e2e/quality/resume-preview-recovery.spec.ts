import { expect, test, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { mockEngineAncillaryApi } from './engine-fixtures'

if (process.env.ENGINE_QA_CHROME === '1') test.use({ channel: 'chrome' })
const digest = (text: string) => createHash('sha256').update(text).digest('hex')
const original = 'Built internal design system used across 6 product surfaces'

function projection(source: string) {
  const text = source.match(/Built internal design system used across \d+ product surfaces/)?.[0] ?? original
  return { document_id: 'guest', source_mode: 'imported', content_revision: 1, source_sha256: digest(source),
    structured_version: null, template_id: null, opaque_blocks: [], nodes: [{ node_id: 'guest-bullet',
      node_revision: digest(text), section: 'Experience', kind: 'bullet', text, editable: true, ai_editable: false,
      source_span: { start: source.indexOf(text), end: source.indexOf(text) + text.length } }] }
}

async function mockGuest(page: Page) {
  await mockEngineAncillaryApi(page, 'changed-account')
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.routeWebSocket('**/ws/jobs**', socket => socket.close())
  await page.route('**/config/feature-flags', route => route.fulfill({ json: {} }))
  await page.route('**/tenants/resolve-host**', route => route.fulfill({ json: { tenant: null } }))
  await page.route('**/public/trial-status**', route => route.fulfill({ json: { usageCount: 0, remainingUses: 3, blocked: false, canUse: true, trialLimit: 3 } }))
  await page.route('**/ats/quick-score', route => route.fulfill({ json: { score: 80 } }))
  await page.route('**/public/engine/document', route => {
    const { latex_content } = route.request().postDataJSON()
    return route.fulfill({ json: { document: projection(latex_content), latex_content } })
  })
  return errors
}

test('acknowledged guest cancellation allows the next saved field to preview without a terminal socket event', async ({ page }, testInfo) => {
  const errors = await mockGuest(page)
  const submissions: Array<{ latex_content: string }> = []
  let cancellations = 0
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: null }))
  await page.route('**/public/engine/document/patch', route => {
    const body = route.request().postDataJSON()
    const source = body.latex_content.replace(projection(body.latex_content).nodes[0].text, body.patches[0].text)
    return route.fulfill({ json: { document: projection(source), latex_content: source } })
  })
  await page.route('**/jobs/submit', route => {
    submissions.push(route.request().postDataJSON())
    return route.fulfill({ json: { success: true, job_id: `cancel-preview-${submissions.length}`, message: 'Queued' } })
  })
  await page.route('**/jobs/cancel-preview-*/state', route => route.fulfill({ json: { status: 'processing', stage: 'latex_compilation', percent: 20, last_updated: Date.now() / 1000 } }))
  await page.route(/\/jobs\/cancel-preview-\d+$/, route => {
    expect(route.request().method()).toBe('DELETE')
    cancellations++
    return route.fulfill({ json: { success: true } })
  })
  await page.goto('/try')
  await page.getByRole('button', { name: new RegExp(original) }).click()
  await page.getByLabel('Experience · bullet').fill(original.replace('6 product', '8 product'))
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(1)
  if (testInfo.project.metadata.mobile) await page.getByRole('button', { name: 'PDF', exact: true }).click()
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect.poll(() => cancellations).toBe(1)
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
  if (testInfo.project.metadata.mobile) await page.getByRole('button', { name: 'Editor', exact: true }).click()
  await page.getByLabel('Experience · bullet').fill(original.replace('6 product', '9 product'))
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(2)
  expect(submissions[1].latex_content).toContain('9 product surfaces')
  expect(errors).toEqual([])
})

test('a delayed guest field patch cannot apply after the account changes with the same source buffer', async ({ page }) => {
  const errors = await mockGuest(page)
  let signedIn = false
  let sessionReads = 0
  let submissions = 0
  let patchReceived = false
  let releasePatch!: () => void
  const heldPatch = new Promise<void>(resolve => { releasePatch = resolve })
  await page.route('**/api/auth/get-session', route => {
    sessionReads++
    return route.fulfill({ json: signedIn ? { session: { token: 'changed-account-token' },
      user: { id: 'changed-account', email: 'changed-account@example.com', name: 'Changed Account' } } : null })
  })
  await page.route('**/public/engine/document/patch', async route => {
    const body = route.request().postDataJSON()
    patchReceived = true
    await heldPatch
    const source = body.latex_content.replace(original, body.patches[0].text)
    await route.fulfill({ json: { document: projection(source), latex_content: source } })
  })
  await page.route('**/jobs/submit', route => { submissions++; return route.fulfill({ json: { success: true, job_id: 'unexpected', message: 'Queued' } }) })
  await page.goto('/try')
  await page.getByRole('button', { name: new RegExp(original) }).click()
  await page.getByLabel('Experience · bullet').fill(original.replace('6 product', '8 product'))
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect.poll(() => patchReceived).toBe(true)
  const previousReads = sessionReads
  signedIn = true
  // Better Auth's actual cross-tab session notification path refreshes the
  // session without remounting the editor or changing its source content.
  await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', {
    key: 'better-auth.message', newValue: JSON.stringify({ event: 'session', data: { trigger: 'updateUser' } }),
  })))
  await expect.poll(() => sessionReads).toBeGreaterThan(previousReads)
  await expect(page.locator('a[title="Dashboard"]')).toBeVisible()
  releasePatch()
  await expect(page.getByRole('alert').filter({ hasText: 'This field could not be saved' })).toBeVisible()
  await expect(page.getByRole('button', { name: new RegExp(original) })).toBeVisible()
  expect(submissions).toBe(0)
  expect(errors).toEqual([])
})
