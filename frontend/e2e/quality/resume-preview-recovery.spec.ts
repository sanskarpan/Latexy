import { expect, test, type Page } from './quality-test'
import { mockEngineAncillaryApi } from './engine-fixtures'
import { applyGuestBulletPatch, GUEST_ORIGINAL_BULLET, projectGuestBullet } from './guest-engine-fixture'

if (process.env.ENGINE_QA_CHROME === '1') test.use({ channel: 'chrome' })
const editedBullet = (count: number) => `Built internal design system used across ${count} product surfaces`

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
    return route.fulfill({ json: { document: projectGuestBullet(latex_content), latex_content } })
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
    return route.fulfill({ json: applyGuestBulletPatch(body) })
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
  await page.getByRole('button', { name: `Experience · bullet ${GUEST_ORIGINAL_BULLET}`, exact: true }).click()
  await page.getByLabel('Experience · bullet').fill(editedBullet(8))
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(1)
  expect(submissions[0].latex_content).toContain(editedBullet(8))
  if (testInfo.project.metadata.mobile) await page.getByRole('button', { name: 'PDF', exact: true }).click()
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect.poll(() => cancellations).toBe(1)
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
  if (testInfo.project.metadata.mobile) await page.getByRole('button', { name: 'Editor', exact: true }).click()
  await page.getByLabel('Experience · bullet').fill(editedBullet(9))
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(2)
  expect(submissions[1].latex_content).toContain('9 product surfaces')
  expect(submissions[1].latex_content).toBe(submissions[0].latex_content.replace(editedBullet(8), editedBullet(9)))
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
    await route.fulfill({ json: applyGuestBulletPatch(body) })
  })
  await page.route('**/jobs/submit', route => { submissions++; return route.fulfill({ json: { success: true, job_id: 'unexpected', message: 'Queued' } }) })
  await page.goto('/try')
  await page.getByRole('button', { name: `Experience · bullet ${GUEST_ORIGINAL_BULLET}`, exact: true }).click()
  await page.getByLabel('Experience · bullet').fill(editedBullet(8))
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
  await expect(page.getByRole('button', { name: `Experience · bullet ${GUEST_ORIGINAL_BULLET}`, exact: true })).toBeVisible()
  expect(submissions).toBe(0)
  expect(errors).toEqual([])
})

for (const { trigger, roundTrip } of [
  { trigger: 'manual', roundTrip: false },
  { trigger: 'automatic', roundTrip: false },
  { trigger: 'trim', roundTrip: false },
  { trigger: 'manual', roundTrip: true },
] as const) {
  test(`an ${roundTrip ? 'A → B → A round-trip' : 'account change'} releases a pending ${trigger} admission without letting its late response disturb the next submit`, async ({ page }, testInfo) => {
    const errors = await mockGuest(page)
    let signedIn = false
    let sessionReads = 0
    const submissions: Array<{ latex_content: string; job_type: string }> = []
    const stateReads: string[] = []
    let releaseOld!: () => void
    let releaseNew!: () => void
    const oldAdmission = new Promise<void>(resolve => { releaseOld = resolve })
    const newAdmission = new Promise<void>(resolve => { releaseNew = resolve })
    await page.route('**/api/auth/get-session', route => {
      sessionReads++
      return route.fulfill({ json: signedIn ? { session: { token: 'changed-account-token' },
        user: { id: 'changed-account', email: 'changed-account@example.com', name: 'Changed Account' } } : null })
    })
    await page.route('**/public/engine/document/patch', route => {
      const body = route.request().postDataJSON()
      return route.fulfill({ json: applyGuestBulletPatch(body) })
    })
    await page.route('**/jobs/submit', async route => {
      const index = submissions.push(route.request().postDataJSON())
      await (index === 1 ? oldAdmission : newAdmission)
      await route.fulfill({ json: { success: true, job_id: index === 1 ? 'stale-admission' : 'current-admission', message: 'Queued' } })
    })
    await page.route(/\/jobs\/(stale|current)-admission\/state$/, route => {
      stateReads.push(new URL(route.request().url()).pathname)
      return route.fulfill({ json: { status: 'processing', stage: 'latex_compilation', percent: 20, last_updated: Date.now() / 1000 } })
    })
    const saveField = async (count: number) => {
      if (testInfo.project.metadata.mobile) await page.getByRole('button', { name: 'Editor', exact: true }).click()
      await page.getByRole('button', { name: /^Experience · bullet / }).click()
      await page.getByLabel('Experience · bullet').fill(editedBullet(count))
      await page.getByRole('button', { name: 'Save field', exact: true }).click()
    }
    try {
      await page.goto('/try')
      const updatePdf = page.getByRole('button', { name: 'Update PDF', exact: true })
      await expect(updatePdf).toBeEnabled()
      if (trigger === 'automatic') await saveField(8)
      else if (trigger === 'trim') {
        if (testInfo.project.metadata.mobile) await page.getByRole('button', { name: 'Tools', exact: true }).click()
        await page.getByRole('button', { name: 'AI Optimize', exact: true }).click()
        await page.getByRole('button', { name: 'Trim to one page', exact: true }).click()
      } else await updatePdf.click()
      await expect.poll(() => submissions.length).toBe(1)
      await expect(updatePdf).toBeDisabled()

      const previousReads = sessionReads
      signedIn = true
      await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', {
        key: 'better-auth.message', newValue: JSON.stringify({ event: 'session', data: { trigger: 'updateUser' } }),
      })))
      await expect.poll(() => sessionReads).toBeGreaterThan(previousReads)
      await expect(page.locator('a[title="Dashboard"]')).toBeVisible()
      await expect(updatePdf).toBeEnabled()
      if (roundTrip) {
        const signedInReads = sessionReads
        signedIn = false
        await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', {
          key: 'better-auth.message', newValue: JSON.stringify({ event: 'session', data: { trigger: 'signOut' } }),
        })))
        await expect.poll(() => sessionReads).toBeGreaterThan(signedInReads)
        await expect(page.locator('a[title="Dashboard"]')).toHaveCount(0)
        await expect(page.getByRole('link', { name: 'Log in', exact: true })).toBeVisible()
        await expect(updatePdf).toBeEnabled()
      }
      // Exercise both new-account entry points while the old admission is held.
      if (trigger === 'manual') await saveField(9)
      else await updatePdf.click()
      await expect.poll(() => submissions.length).toBe(2)
      await expect(updatePdf).toBeDisabled()
      expect(stateReads).toEqual([])

      const oldResponse = page.waitForResponse(response => response.url().endsWith('/jobs/submit'))
      releaseOld()
      await (await oldResponse).finished()
      // Cross a render boundary after delivering the old response, without a
      // fixed sleep or ever releasing the current admission as a side effect.
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
      await expect(updatePdf).toBeDisabled()
      expect(stateReads).toEqual([])
      expect(submissions).toHaveLength(2)
      await expect(page.getByText('Job submitted.', { exact: true })).toHaveCount(0)
      await expect(page.getByText('Trimming to 1 page…', { exact: true })).toHaveCount(0)

      releaseNew()
      await expect.poll(() => stateReads.some(path => path.endsWith('/current-admission/state'))).toBe(true)
      if (testInfo.project.metadata.mobile) await page.getByRole('button', { name: 'PDF', exact: true }).click()
      await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
      expect(stateReads.some(path => path.endsWith('/stale-admission/state'))).toBe(false)
      expect(errors).toEqual([])
    } finally {
      releaseOld()
      releaseNew()
    }
  })
}
