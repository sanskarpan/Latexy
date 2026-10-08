import { expect, test } from '@playwright/test'

const TEMPLATES = [{
  id: '11111111-1111-1111-1111-111111111111',
  name: 'ATS Guided',
  description: 'ATS-safe single column template',
  category: 'ats_safe',
  category_label: 'ATS-Safe',
  sort_order: 0,
  thumbnail_url: null,
  pdf_url: null,
  template_family: 'ats',
}]

test.describe('guided builder ownership boundaries', () => {
  test('does not navigate an owner B session from a deferred owner A create', async ({ page }) => {
    let owner = 'owner-a'
    let sessionCalls = 0
    const sessionOwners: string[] = []
    let createStarted = false
    let releaseCreate!: () => void
    const createGate = new Promise<void>(resolve => {
      releaseCreate = resolve
    })

    await page.route('**/api/auth/get-session', route => {
      sessionCalls += 1
      sessionOwners.push(owner)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { id: `session-${owner}`, userId: owner, token: `token-${owner}`, expiresAt: '2099-01-01T00:00:00Z' },
          user: { id: owner, email: `${owner}@example.com`, name: owner },
        }),
      })
    })
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => {
      const templates = TEMPLATES.map(template => ({ ...template, name: `${owner} template` }))
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(templates),
      })
    })
    let createResponseFinished = false
    await page.route('**/resumes/builder', async route => {
      if (route.request().method() !== 'POST') return route.fallback()
      createStarted = true
      await createGate
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          resume: {
            id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            user_id: 'owner-a',
            title: 'Owner A draft',
            builder_status: 'active',
            structured_content: {},
          },
          template_family: 'ats',
        }),
      })
      createResponseFinished = true
    })

    await page.goto('/workspace/builder/new', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Create your résumé' })).toBeVisible()
    await page.locator('input[placeholder*="Senior Backend Engineer"]').fill('Owner A draft')
    await page.getByRole('button', { name: 'Start my résumé' }).click()
    await expect.poll(() => createStarted).toBe(true)

    owner = 'owner-b'
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-owner-switch' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await expect.poll(() => sessionOwners).toContain('owner-b')
    await expect(page.getByRole('heading', { name: 'owner-b template', level: 3, exact: true })).toBeVisible()

    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    try {
      releaseCreate()
      await expect.poll(() => createResponseFinished).toBe(true)
      await page.evaluate(() => new Promise<void>(resolve => {
        requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
      }))

      await expect(page).toHaveURL(/\/workspace\/builder\/new$/)
      await expect(page.getByRole('heading', { name: 'Create your résumé' })).toBeVisible()
    } finally {
      releaseCreate()
    }
  })

  test('same-owner create still navigates to the returned draft', async ({ page }) => {
    await page.route('**/api/auth/get-session', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'session-owner-a', userId: 'owner-a', token: 'token-owner-a', expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: 'owner-a', email: 'owner-a@example.com', name: 'Owner A' },
      }),
    }))
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(TEMPLATES),
    }))
    await page.route('**/resumes/builder', async route => {
      if (route.request().method() !== 'POST') return route.fallback()
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          resume: {
            id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
            user_id: 'owner-a',
            title: 'Owner A draft',
            builder_status: 'active',
            structured_content: {},
          },
          template_family: 'ats',
        }),
      })
    })

    await page.goto('/workspace/builder/new', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Create your résumé' })).toBeVisible()
    await page.locator('input[placeholder*="Senior Backend Engineer"]').fill('Owner A draft')
    await page.getByRole('button', { name: 'Start my résumé' }).click()
    await expect(page).toHaveURL(/\/workspace\/builder\/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb$/)
  })

  test('preserves the same-owner draft across a transient auth refresh error', async ({ page }) => {
    let sessionMode: 'ok' | 'error' = 'ok'
    let sessionCalls = 0
    let createCalls = 0
    let errorResponseFinished = false
    let recoveryResponseFinished = false
    await page.route('**/api/auth/get-session', route => {
      sessionCalls += 1
      if (sessionMode === 'error') {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary auth failure' }) }).then(() => {
          errorResponseFinished = true
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { id: 'session-owner-a', userId: 'owner-a', token: 'token-owner-a', expiresAt: '2099-01-01T00:00:00Z' },
          user: { id: 'owner-a', email: 'owner-a@example.com', name: 'Owner A' },
        }),
      }).then(() => {
        if (sessionMode === 'ok' && sessionCalls > 1) recoveryResponseFinished = true
      })
    })
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(TEMPLATES),
    }))
    await page.route('**/resumes/builder', async route => {
      if (route.request().method() !== 'POST') return route.fallback()
      createCalls += 1
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          resume: { id: 'cccccccc-cccc-cccc-cccc-cccccccccccc', user_id: 'owner-a', title: 'Draft survives auth refresh', builder_status: 'active', structured_content: {} },
          template_family: 'ats',
        }),
      })
    })

    await page.goto('/workspace/builder/new', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Create your résumé' })).toBeVisible()
    const title = page.locator('input[placeholder*="Senior Backend Engineer"]')
    await title.fill('Draft survives auth refresh')

    sessionMode = 'error'
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-transient-error' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await expect.poll(() => errorResponseFinished).toBe(true)
    await expect(title).toHaveValue('Draft survives auth refresh')
    await expect(page.getByRole('heading', { name: 'Create your résumé' })).toBeVisible()
    await page.getByRole('button', { name: 'Start my résumé' }).click()
    await expect(page.getByText('Session verification is still in progress. Please try again.')).toBeVisible()
    expect(createCalls).toBe(0)

    sessionMode = 'ok'
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-retry' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => sessionCalls).toBeGreaterThan(2)
    await expect.poll(() => recoveryResponseFinished).toBe(true)
    await expect(title).toHaveValue('Draft survives auth refresh')
    await page.getByRole('button', { name: 'Start my résumé' }).click()
    await expect(page).toHaveURL(/\/workspace\/builder\/cccccccc-cccc-cccc-cccc-cccccccccccc$/)
    expect(createCalls).toBe(1)
  })
})
