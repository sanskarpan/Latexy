import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

function resumeResponse(owner: string) {
  return {
    id: RESUME_ID,
    user_id: owner,
    title: owner === 'owner-a' ? 'Owner A resume' : 'Owner B resume',
    latex_content: 'short resume content',
    is_template: false,
    parent_resume_id: null,
    metadata: { last_persona: owner === 'owner-a' ? '' : 'enterprise' },
    created_at: '2026-05-29T00:00:00Z',
    updated_at: '2026-05-29T00:00:00Z',
  }
}

async function switchOwner(page: Page, owner: { value: string }, nextOwner: string) {
  owner.value = nextOwner
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test-owner-switch' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
}

function installSession(page: Page, owner: { value: string }, onResponse: () => void) {
  return page.route('**/api/auth/get-session', route => {
    const currentOwner = owner.value
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: `session-${currentOwner}`, userId: currentOwner, token: `token-${currentOwner}`, expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: currentOwner, email: `${currentOwner}@example.com`, name: currentOwner },
      }),
    }).then(onResponse)
  })
}

function expectActivePersona(page: Page, label: string) {
  return expect(page.getByRole('button', { name: new RegExp(label) })).toHaveClass(/border-accent/)
}

test.describe('optimization owner-scoped settings', () => {
  test('does not let a deferred owner-A persona failure overwrite owner-B state', async ({ page }) => {
    const owner = { value: 'owner-a' }
    let sessionResponses = 0
    let settingsStarted = false
    let settingsFinished = false
    let settingsCalls = 0
    let releaseSettings!: () => void
    const settingsGate = new Promise<void>(resolve => { releaseSettings = resolve })

    await installSession(page, owner, () => { sessionResponses += 1 })
    await page.route('**/ws/**', route => route.abort())
    await page.route(`**/resumes/${RESUME_ID}`, async route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resumeResponse(owner.value)) })
      }
      return route.fallback()
    })
    await page.route(`**/resumes/${RESUME_ID}/settings`, async route => {
      settingsCalls += 1
      if (owner.value === 'owner-a' && settingsCalls === 1) {
        settingsStarted = true
        await settingsGate
        await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'owner-A settings request expired' }) })
        settingsFinished = true
        return
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resumeResponse(owner.value)) })
    })

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Optimize "Owner A resume"')).toBeVisible()
    await page.getByRole('button', { name: /Startup \/ Scale-up/ }).click()
    await expectActivePersona(page, 'Startup / Scale-up')
    await expect.poll(() => settingsStarted).toBe(true)

    await switchOwner(page, owner, 'owner-b')
    await expect.poll(() => sessionResponses).toBeGreaterThan(1)
    await expect(page.getByText('Optimize "Owner B resume"')).toBeVisible()
    // The new owner’s persisted enterprise persona is loaded before the old
    // owner’s deferred request is released. Change it to startup so this test
    // also proves the new owner is not left mutation-locked by the old write.
    await expectActivePersona(page, 'Enterprise / Corporate')
    await page.getByRole('button', { name: /Startup \/ Scale-up/ }).click()
    await expect.poll(() => settingsCalls).toBe(2)
    await expectActivePersona(page, 'Startup / Scale-up')

    try {
      releaseSettings()
      await expect.poll(() => settingsFinished).toBe(true)
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))))
      await expectActivePersona(page, 'Startup / Scale-up')
    } finally {
      releaseSettings()
    }
  })

  test('same-owner persona settings response remains accepted', async ({ page }) => {
    let settingsCalls = 0
    await page.route('**/api/auth/get-session', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'session-owner-a', userId: 'owner-a', token: 'token-owner-a', expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: 'owner-a', email: 'owner-a@example.com', name: 'Owner A' },
      }),
    }))
    await page.route('**/ws/**', route => route.abort())
    await page.route(`**/resumes/${RESUME_ID}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resumeResponse('owner-a')) }))
    await page.route(`**/resumes/${RESUME_ID}/settings`, route => {
      settingsCalls += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resumeResponse('owner-a')) })
    })

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Optimize "Owner A resume"')).toBeVisible()
    await page.getByRole('button', { name: /Startup \/ Scale-up/ }).click()
    await expect.poll(() => settingsCalls).toBe(1)
    await expectActivePersona(page, 'Startup / Scale-up')
  })

  test('same-owner auth revalidation does not strand a failed persona mutation', async ({ page }) => {
    let sessionMode: 'ok' | 'error' = 'ok'
    let sessionResponses = 0
    let refreshStarted = false
    let releaseRefresh!: () => void
    const refreshGate = new Promise<void>(resolve => { releaseRefresh = resolve })
    let errorResponseFinished = false
    let recoveryResponseFinished = false
    let settingsStarted = false
    let settingsFinished = false
    let settingsCalls = 0
    let releaseSettings!: () => void
    const settingsGate = new Promise<void>(resolve => { releaseSettings = resolve })

    await page.route('**/api/auth/get-session', async route => {
      sessionResponses += 1
      if (sessionResponses === 2) {
        refreshStarted = true
        await refreshGate
      }
      if (sessionMode === 'error') {
        await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary auth failure' }) })
        errorResponseFinished = true
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { id: 'session-owner-a', userId: 'owner-a', token: 'token-owner-a', expiresAt: '2099-01-01T00:00:00Z' },
          user: { id: 'owner-a', email: 'owner-a@example.com', name: 'Owner A' },
        }),
      })
      if (sessionResponses > 1) recoveryResponseFinished = true
    })
    await page.route('**/ws/**', route => route.abort())
    await page.route(`**/resumes/${RESUME_ID}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resumeResponse('owner-a')) }))
    await page.route(`**/resumes/${RESUME_ID}/settings`, async route => {
      settingsCalls += 1
      if (settingsCalls === 1) {
        settingsStarted = true
        await settingsGate
        settingsFinished = true
        await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'settings request expired during auth revalidation' }) })
        return
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resumeResponse('owner-a')) })
    })

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Optimize "Owner A resume"')).toBeVisible()
    await page.getByRole('button', { name: /Startup \/ Scale-up/ }).click()
    await expect.poll(() => settingsStarted).toBe(true)

    sessionMode = 'error'
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-auth-refresh' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => refreshStarted).toBe(true)
    releaseRefresh()
    await expect.poll(() => errorResponseFinished).toBe(true)

    releaseSettings()
    await expect.poll(() => settingsFinished).toBe(true)
    // The failed write may restore the persisted value; cleanup must release
    // the busy gate even though auth is currently in an error state.
    await expect(page.getByRole('button', { name: /Enterprise \/ Corporate/ })).toBeEnabled()

    sessionMode = 'ok'
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-auth-recovery' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => sessionResponses).toBe(3)
    await expect.poll(() => recoveryResponseFinished).toBe(true)
    await page.getByRole('button', { name: /Enterprise \/ Corporate/ }).click()
    await expect.poll(() => settingsCalls).toBe(2)
    await expectActivePersona(page, 'Enterprise / Corporate')
  })
})
