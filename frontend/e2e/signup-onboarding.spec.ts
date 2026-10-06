import { expect, test, type Page, type Route } from '@playwright/test'

async function mockAuthenticatedNewUser(page: Page, onPreferenceUpdate: (body: unknown) => void) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'signup-onboarding-session', userId: 'signup-onboarding-user', token: 'token' },
        user: {
          id: 'signup-onboarding-user',
          email: 'new-user@example.com',
          name: 'New User',
        },
      }),
    }),
  )

  const backendPaths = new Set([
    '/me',
    '/me/preferences',
    '/resumes/',
    '/jobs/',
    '/resumes/stats',
    '/subscription/plans',
    '/config/feature-flags',
    '/config/entitlements',
    '/tenants/resolve-host',
  ])
  await page.route((url) => backendPaths.has(url.pathname), async (route: Route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    if (path === '/me' && request.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'signup-onboarding-user',
          email: 'new-user@example.com',
          plan: 'free',
          role: 'user',
          preferences: { has_onboarded: false },
        }),
      })
    }
    if (path === '/me/preferences' && request.method() === 'PATCH') {
      onPreferenceUpdate(request.postDataJSON())
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'signup-onboarding-user',
          email: 'new-user@example.com',
          plan: 'free',
          role: 'user',
          preferences: { has_onboarded: true },
        }),
      })
    }
    if (path === '/resumes/' && request.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ resumes: [], total: 0, page: 1, limit: 20, pages: 0 }),
      })
    }
    if (path === '/jobs/' && request.method() === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"jobs":[]}' })
    }
    if (path === '/resumes/stats') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_resumes: 0,
          total_templates: 0,
          last_updated: null,
          avg_ats_score: null,
          best_ats_score: null,
          optimized_count: 0,
        }),
      })
    }
    if (path === '/subscription/plans') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          plans: { free: { compilations: 10, optimizations: 3 } },
        }),
      })
    }

    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
}

test.describe('Sign-up form', () => {
  test('rejects mismatched passwords before sending credentials', async ({ page }) => {
    let submitted = false
    await page.route('**/api/auth/sign-up/email', (route) => {
      submitted = true
      return route.fulfill({ status: 500, body: 'must not be called' })
    })

    await page.goto('/signup')
    await page.getByLabel('Full Name').fill('New User')
    await page.getByLabel('Email').fill('new-user@example.com')
    await page.getByLabel('Password', { exact: true }).fill('StrongPass1!')
    await page.getByLabel('Confirm Password').fill('Different1!')
    await page.getByRole('button', { name: 'Sign Up' }).click()

    await expect(page.getByText('Passwords do not match.').first()).toBeVisible()
    expect(submitted).toBe(false)
  })

  test('surfaces an existing-account error and releases the form for retry', async ({ page }) => {
    let submissions = 0
    await page.route('**/api/auth/sign-up/email', (route) => {
      submissions += 1
      return route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'USER_ALREADY_EXISTS', message: 'User already exists' }),
      })
    })

    await page.goto('/signup')
    await page.getByLabel('Full Name').fill('Existing User')
    await page.getByLabel('Email').fill('existing@example.com')
    await page.getByLabel('Password', { exact: true }).fill('StrongPass1!')
    await page.getByLabel('Confirm Password').fill('StrongPass1!')
    await page.getByRole('button', { name: 'Sign Up' }).click()

    await expect(page.locator('#signup-error')).toContainText(
      'An account with that email already exists. Try signing in instead.',
    )
    await expect(page.getByRole('button', { name: 'Sign Up' })).toBeEnabled()
    expect(submissions).toBe(1)
  })

  test('rejects an external post-signup redirect', async ({ page }) => {
    await page.goto('/signup?redirect=https%3A%2F%2Fevil.example%2Fsteal')
    await expect(page.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  })
})

test('new users can complete onboarding and persist it to their account', async ({ page }) => {
  let preferenceUpdate: unknown = null
  await mockAuthenticatedNewUser(page, (body) => {
    preferenceUpdate = body
  })
  await page.addInitScript(() => localStorage.removeItem('latexy_onboarding_completed'))

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  const dialog = page.getByRole('dialog', { name: 'Welcome to Latexy' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('parse-clean')

  await dialog.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('dialog', { name: 'How Latexy works' })).toBeVisible()
  await page.getByRole('dialog', { name: 'How Latexy works' })
    .getByRole('button', { name: 'Next', exact: true })
    .click()
  await expect(page.getByRole('dialog', { name: 'What you get' })).toBeVisible()
  await page.getByRole('dialog', { name: 'What you get' })
    .getByRole('button', { name: 'Next', exact: true })
    .click()
  await expect(page.getByRole('dialog', { name: "You're all set" })).toBeVisible()
  await page.getByRole('button', { name: 'Get started' }).click()

  await expect(page.getByRole('dialog')).toBeHidden()
  await expect.poll(() => preferenceUpdate).toEqual({ has_onboarded: true })
  await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_onboarding_completed')))
    .toBe('true')
})
