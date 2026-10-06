import { expect, test, type Page, type Route } from '@playwright/test'

const session = {
  session: { id: 'institution-session', userId: 'owner-1', token: 'owner-token' },
  user: { id: 'owner-1', email: 'owner@example.edu', name: 'Owner' },
}

async function mockSession(page: Page) {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(session),
  }))
  await page.route((url) => ['/config/feature-flags', '/config/entitlements'].includes(url.pathname), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/me', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'owner-1', email: 'owner@example.edu', role: 'admin', plan: 'team' }),
  }))
}

test('institution admin can inspect cohorts, verify DNS, and send a pending invitation', async ({ page }) => {
  await mockSession(page)
  const tenant = {
    id: 'tenant-1', slug: 'example-university', name: 'Example University',
    logo_url: null, primary_color: '#0055aa', custom_domain: 'cv.example.edu',
    domain_verified: false, plan_id: 'university', max_members: 200, active: true,
    owner_id: 'owner-1', created_at: '2026-09-01T00:00:00Z',
  }
  let inviteBody: unknown = null
  await page.route((url) => url.pathname.startsWith('/tenants'), async (route: Route) => {
    const { pathname } = new URL(route.request().url())
    if (pathname === '/tenants/resolve-host') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ tenant: null }) })
    if (pathname === '/tenants/my') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([tenant]) })
    if (pathname === '/tenants/tenant-1/members' && route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ user_id: 'owner-1', email: 'owner@example.edu', name: 'Owner', role: 'admin', joined_at: '2026-09-01T00:00:00Z' }]) })
    if (pathname === '/tenants/tenant-1/stats') return route.fulfill({ status: 200, contentType: 'application/json', body: '{"member_count":1}' })
    if (pathname === '/tenants/tenant-1/cohorts') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'cohort-1', name: 'Class of 2027', member_count: 12, resume_count: 4, created_at: '2026-09-01T00:00:00Z' }]) })
    if (pathname.endsWith('/submissions')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ resume_id: 'resume-1', title: 'Graduate CV', student_user_id: 'student-1', student_email: 'student@example.edu', student_name: 'Student One', started_at: '2026-09-02T00:00:00Z', opened_at: '2026-09-03T00:00:00Z', downloaded_at: null }]) })
    if (pathname.endsWith('/domain/verify')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ domain: 'cv.example.edu', verified: true, txt_record_name: '_latexy.cv.example.edu', txt_record_value: 'latexy-verify=tenant-1', instructions: 'Verified.' }) })
    if (pathname.endsWith('/members/invite')) {
      inviteBody = route.request().postDataJSON()
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ email: 'student@example.edu', role: 'member', cohort_id: 'cohort-1', expires_in_seconds: 604800, message: 'Tenant invitation created' }) })
    }
    return route.fulfill({ status: 404, body: '{}' })
  })

  await page.goto('/admin/tenant')
  await expect(page.getByRole('heading', { name: 'Tenant Management' })).toBeVisible()
  await expect(page.getByText('Class of 2027', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Refresh milestones' }).click()
  await expect(page.getByText('Student One')).toBeVisible()
  await expect(page.getByText('Graduate CV')).toBeVisible()

  await page.getByRole('button', { name: 'Verify DNS' }).click()
  await expect(page.getByText('Domain verified')).toBeVisible()

  await page.getByPlaceholder('colleague@example.com').fill('student@example.edu')
  await page.getByLabel('Cohort for invited member').selectOption('cohort-1')
  await page.getByRole('button', { name: 'Invite' }).click()
  await expect.poll(() => inviteBody).toEqual({
    email: 'student@example.edu', role: 'member', cohort_id: 'cohort-1',
  })
})

test('login discovers an operator-configured institutional OIDC provider', async ({ page }) => {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: 'null' }))
  await page.route('**/api/auth/providers', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ oidc: { id: 'university_sso', label: 'Example University' } }),
  }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"tenant":null}' }))

  await page.goto('/login')
  await expect(page.getByRole('button', { name: 'Continue with Example University' })).toBeVisible()
})

test('tenant invitation preserves login return and accepts for the signed-in email', async ({ page }) => {
  await mockSession(page)
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"tenant":null}' }))
  let acceptCount = 0
  await page.route((url) => url.pathname === '/tenants/invitations/safe-token/accept', (route) => {
    acceptCount += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user_id: 'owner-1', email: 'owner@example.edu', name: 'Owner', role: 'member', joined_at: '2026-09-12T00:00:00Z' }),
    })
  })

  await page.goto('/tenant-invite?token=safe-token')
  await expect(page.getByRole('heading', { name: 'Review your invitation' })).toBeVisible()
  expect(acceptCount).toBe(0)
  await page.getByRole('button', { name: 'Accept invitation' }).click()
  await expect(page.getByRole('heading', { name: 'Invitation accepted' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open workspace' })).toBeVisible()
  expect(acceptCount).toBe(1)
})

test('tenant invitation keeps a transient acceptance failure retryable', async ({ page }) => {
  await mockSession(page)
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"tenant":null}' }))
  let acceptCount = 0
  await page.route((url) => url.pathname === '/tenants/invitations/retry-token/accept', (route) => {
    acceptCount += 1
    if (acceptCount === 1) {
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Invitation service is temporarily unavailable' }) })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user_id: 'owner-1', email: 'owner@example.edu', name: 'Owner', role: 'member', joined_at: '2026-09-12T00:00:00Z' }),
    })
  })

  await page.goto('/tenant-invite?token=retry-token')
  await page.getByRole('button', { name: 'Accept invitation' }).click()
  await expect(page.getByRole('heading', { name: 'Invitation not accepted' })).toBeVisible()
  await expect(page.getByText(/HTTP 503: Invitation service is temporarily unavailable/)).toBeVisible()
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('heading', { name: 'Invitation accepted' })).toBeVisible()
  expect(acceptCount).toBe(2)
})

test('tenant invitation removes the acceptance CTA after a terminal account mismatch', async ({ page }) => {
  await mockSession(page)
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"tenant":null}' }))
  await page.route((url) => url.pathname === '/tenants/invitations/mismatch-token/accept', (route) => route.fulfill({
    status: 403,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Invitation email does not match this account' }),
  }))

  await page.goto('/tenant-invite?token=mismatch-token')
  await page.getByRole('button', { name: 'Accept invitation' }).click()
  await expect(page.getByRole('heading', { name: 'Invitation not accepted' })).toBeVisible()
  await expect(page.getByText(/HTTP 403: Invitation email does not match this account/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Try again' })).toBeHidden()
  await expect(page.getByRole('button', { name: 'Accept invitation' })).toBeHidden()
})

test('tenant invitation ignores a pending acceptance after the token changes', async ({ page }) => {
  await mockSession(page)
  let releaseOldAcceptance = () => {}
  const oldAcceptanceReleased = new Promise<void>((resolve) => { releaseOldAcceptance = resolve })
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"tenant":null}' }))
  await page.route((url) => url.pathname.endsWith('/accept'), async (route) => {
    const pathParts = new URL(route.request().url()).pathname.split('/')
    const token = pathParts[pathParts.length - 2]
    if (token === 'old-token') {
      await oldAcceptanceReleased
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user_id: 'owner-1', email: 'owner@example.edu', name: 'Owner', role: 'member', joined_at: '2026-09-12T00:00:00Z' }),
    })
  })

  await page.goto('/tenant-invite?token=old-token')
  await page.getByRole('button', { name: 'Accept invitation' }).click()
  await page.evaluate(() => window.history.pushState({}, '', '/tenant-invite?token=new-token'))
  await expect(page.getByRole('heading', { name: 'Review your invitation' })).toBeVisible()
  releaseOldAcceptance()
  await expect(page.getByRole('heading', { name: 'Invitation accepted' })).toBeHidden()
  await expect(page.getByRole('button', { name: 'Accept invitation' })).toBeVisible()
})

test('tenant invitation offers account creation with the exact return URL', async ({ page }) => {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: 'null',
  }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"tenant":null}',
  }))

  await page.goto('/tenant-invite?token=new-student-token')
  await expect(page.getByRole('link', { name: 'Sign in' })).toHaveAttribute(
    'href',
    '/login?redirect=%2Ftenant-invite%3Ftoken%3Dnew-student-token',
  )
  await expect(page.getByRole('link', { name: 'Create an account' })).toHaveAttribute(
    'href',
    '/signup?redirect=%2Ftenant-invite%3Ftoken%3Dnew-student-token',
  )
})

test('tenant cohort editor can open the recruiter dashboard', async ({ page }) => {
  await mockSession(page)
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"tenant":null}',
  }))
  await page.route((url) => url.pathname === '/workspaces/cohort-1', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: 'cohort-1', name: 'Class of 2027', owner_id: 'another-admin', plan_id: 'university',
      max_members: 200, member_count: 2, resume_count: 1, created_at: '2026-09-01T00:00:00Z',
      members: [{ user_id: 'owner-1', email: 'owner@example.edu', role: 'editor' }],
    }),
  }))
  await page.route((url) => url.pathname === '/workspaces/cohort-1/resumes', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'resume-1', title: 'Graduate CV', owner_id: 'student-1', shared_at: '2026-09-02T00:00:00Z',
      opened_at: '2026-09-03T00:00:00Z', downloaded_at: null,
    }]),
  }))
  await page.route((url) => url.pathname === '/workspaces/cohort-1/resumes/resume-1/notes', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname === '/resumes/resume-1/comments', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{
      id: 'comment-1', resume_id: 'resume-1', workspace_id: 'cohort-1', author_id: 'student-1',
      author_name: 'Student One', content: 'Please review this', resolved: false,
      created_at: '2026-09-02T00:00:00Z', updated_at: '2026-09-02T00:00:00Z', mentions: [],
    }]) }))
  await page.route((url) => url.pathname === '/resumes/resume-1/comments/participants', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
      { user_id: 'owner-1', display_name: 'Owner', email: 'owner@example.edu' },
    ]) }))

  await page.goto('/workspaces/cohort-1/recruiter?resume_id=resume-1&comment_id=comment-1')
  await expect(page.getByRole('heading', { name: 'Recruiter Dashboard' })).toBeVisible()
  await expect(page.getByText('Graduate CV')).toBeVisible()
  await expect(page.getByText('Please review this')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Comment' })).toBeVisible()
})
