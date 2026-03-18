import { test, expect, type Page, type Route } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Mock data — IDs must be valid hex UUIDs for route regex matching   //
// ------------------------------------------------------------------ //

const RESUME_NO_SHARE = {
  id: 'aaab0001-0001-0001-0001-000000000001',
  user_id: 'user-share-001',
  title: 'Software Engineer Resume',
  latex_content: '\\documentclass{article}\\begin{document}Hello\\end{document}',
  is_template: false,
  tags: [],
  parent_resume_id: null,
  variant_count: 0,
  share_token: null,
  share_url: null,
  created_at: '2026-03-01T10:00:00Z',
  updated_at: '2026-03-10T10:00:00Z',
  metadata: null,
}

const RESUME_WITH_SHARE = {
  ...RESUME_NO_SHARE,
  id: 'aaab0002-0002-0002-0002-000000000002',
  title: 'Product Manager Resume',
  share_token: 'abc123tok_xyz789',
  share_url: 'http://localhost:5181/r/abc123tok_xyz789',
}

const SHARE_LINK_RESPONSE = {
  share_token: 'newtoken_abc123def456',
  share_url: 'http://localhost:5181/r/newtoken_abc123def456',
  created_at: '2026-03-17T10:00:00Z',
}

const SHARED_RESUME_RESPONSE = {
  resume_title: 'Software Engineer Resume',
  share_token: 'abc123tok_xyz789',
  pdf_url: 'http://localhost:9000/latexy/shares/aaab0001/resume.pdf?sig=test',
  compiled_at: '2026-03-17T09:00:00Z',
}

// ------------------------------------------------------------------ //
//  Auth + API mock helpers                                            //
// ------------------------------------------------------------------ //

async function mockAuth(page: Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'test-session', userId: 'user-share-001', token: 'test-token' },
        user: { id: 'user-share-001', email: 'share@example.com', name: 'Share User' },
      }),
    })
  )
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token-mock')
  })
}

async function mockWorkspaceApi(page: Page, resumes = [RESUME_NO_SHARE, RESUME_WITH_SHARE]) {
  // Abort WebSocket to prevent networkidle from hanging
  await page.route('**/ws/**', (route) => route.abort())

  await page.route((url) => {
    const path = url.pathname
    return (
      path.startsWith('/resumes') ||
      path.startsWith('/jobs') ||
      path.startsWith('/share/') ||
      path.startsWith('/analytics') ||
      path.startsWith('/usage')
    )
  }, async (route: Route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()

    if ((path === '/resumes/' || path === '/resumes') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          resumes,
          total: resumes.length,
          page: 1,
          limit: 20,
          pages: 1,
        }),
      })
    }

    const getResumeMatch = path.match(/^\/resumes\/([0-9a-f-]{36})$/)
    if (getResumeMatch && method === 'GET') {
      const resume = resumes.find((r) => r.id === getResumeMatch[1])
      if (resume) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(resume),
        })
      }
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not found' }),
      })
    }

    const shareMatch = path.match(/^\/resumes\/([0-9a-f-]{36})\/share$/)
    if (shareMatch && method === 'POST') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARE_LINK_RESPONSE),
      })
    }

    if (shareMatch && method === 'DELETE') {
      return route.fulfill({ status: 204 })
    }

    if (path.match(/^\/share\//) && method === 'GET') {
      const token = path.split('/share/')[1]
      if (token === RESUME_WITH_SHARE.share_token) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(SHARED_RESUME_RESPONSE),
        })
      }
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not found or revoked' }),
      })
    }

    if (path === '/jobs' && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ jobs: [] }),
      })
    }

    return route.continue()
  })
}

// Edit page extra mocks (compile job stubs)
async function mockEditPageJobs(page: Page) {
  await page.route('**/jobs/submit', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: 'mock-share-job-001', message: 'ok' }),
    })
  )
  await page.route('**/jobs/mock-share-job-001/state', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'completed',
        stage: 'done',
        percent: 100,
        last_updated: Date.now() / 1000,
      }),
    })
  )
  await page.route('**/ws/**', (route) => route.abort())
}


// ------------------------------------------------------------------ //
//  Workspace page — Share button on resume cards                      //
// ------------------------------------------------------------------ //

test.describe('Workspace — Share button on resume cards', () => {

  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page)
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')
  })

  test('page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.waitForTimeout(1000)
    expect(errors).toEqual([])
  })

  test('resume cards have Share buttons', async ({ page }) => {
    const shareButtons = page.getByRole('button', { name: 'Share' })
    await expect(shareButtons.first()).toBeVisible()
    // Both resumes should have Share buttons
    await expect(shareButtons).toHaveCount(2)
  })

  test('resume with no share token shows inactive Share button', async ({ page }) => {
    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    const shareBtn = noShareCard.getByRole('button', { name: 'Share' })
    await expect(shareBtn).toBeVisible()
    // Inactive = zinc color, not sky
    const cls = await shareBtn.getAttribute('class')
    expect(cls).not.toMatch(/text-sky/)
  })

  test('resume with existing share token shows active Share button', async ({ page }) => {
    const shareCard = page.locator('article').filter({ hasText: 'Product Manager Resume' })
    const shareBtn = shareCard.getByRole('button', { name: 'Share' })
    await expect(shareBtn).toBeVisible()
    // Active = sky color class
    await expect(shareBtn).toHaveClass(/text-sky/)
  })

  test('clicking Share on a resume opens the ShareResumeModal', async ({ page }) => {
    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    await noShareCard.getByRole('button', { name: 'Share' }).click()

    await expect(page.getByRole('heading', { name: 'Share Resume' })).toBeVisible()
  })

  test('share modal shows correct resume title', async ({ page }) => {
    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    await noShareCard.getByRole('button', { name: 'Share' }).click()

    // The modal subtitle includes the resume title
    await expect(page.locator('p').filter({ hasText: 'Software Engineer Resume' }).first()).toBeVisible()
  })
})


// ------------------------------------------------------------------ //
//  ShareResumeModal — generate link                                   //
// ------------------------------------------------------------------ //

test.describe('ShareResumeModal — generate link flow', () => {

  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page)
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')
    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    await noShareCard.getByRole('button', { name: 'Share' }).click()
    await expect(page.getByRole('heading', { name: 'Share Resume' })).toBeVisible()
  })

  test('modal shows Generate button when no share link exists', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Generate shareable link' })).toBeVisible()
  })

  test('modal explains what share link does', async ({ page }) => {
    await expect(page.getByText(/Generate a public link/i)).toBeVisible()
  })

  test('clicking Generate calls POST /resumes/:id/share', async ({ page }) => {
    let shareApiCalled = false
    let shareApiUrl = ''

    page.on('request', (req) => {
      if (req.url().includes('/share') && req.method() === 'POST') {
        shareApiCalled = true
        shareApiUrl = req.url()
      }
    })

    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await page.waitForTimeout(500)

    expect(shareApiCalled).toBe(true)
    expect(shareApiUrl).toContain(RESUME_NO_SHARE.id)
    expect(shareApiUrl).toContain('/share')
  })

  test('after generate, modal shows the share URL', async ({ page }) => {
    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText(SHARE_LINK_RESPONSE.share_url)).toBeVisible()
  })

  test('after generate, modal shows Copy link button', async ({ page }) => {
    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await page.waitForTimeout(500)

    // The modal has 2 "Copy link" buttons: a small icon button + a full-width button
    await expect(page.getByRole('button', { name: 'Copy link' }).first()).toBeVisible()
  })

  test('after generate, modal shows Revoke link option', async ({ page }) => {
    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText('Revoke link')).toBeVisible()
  })

  test('modal shows loading state while generating', async ({ page }) => {
    await page.route(`**/resumes/${RESUME_NO_SHARE.id}/share`, async (route) => {
      await new Promise((r) => setTimeout(r, 500))
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARE_LINK_RESPONSE),
      })
    })

    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await expect(page.getByText('Generating…')).toBeVisible()
  })
})


// ------------------------------------------------------------------ //
//  ShareResumeModal — existing share link (pre-loaded)                //
// ------------------------------------------------------------------ //

test.describe('ShareResumeModal — existing share link state', () => {

  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page)
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')
    const shareCard = page.locator('article').filter({ hasText: 'Product Manager Resume' })
    await shareCard.getByRole('button', { name: 'Share' }).click()
    await expect(page.getByRole('heading', { name: 'Share Resume' })).toBeVisible()
  })

  test('modal immediately shows share URL for resume with existing token', async ({ page }) => {
    await expect(page.getByText(RESUME_WITH_SHARE.share_url!)).toBeVisible()
  })

  test('modal shows Copy link button for existing share', async ({ page }) => {
    // Modal has 2 Copy link buttons: a small icon button + a full-width button
    await expect(page.getByRole('button', { name: 'Copy link' }).first()).toBeVisible()
  })

  test('modal shows Revoke link option for existing share', async ({ page }) => {
    await expect(page.getByText('Revoke link')).toBeVisible()
  })

  test('modal does NOT show Generate button when share exists', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Generate shareable link' })).not.toBeVisible()
  })
})


// ------------------------------------------------------------------ //
//  ShareResumeModal — revoke flow                                     //
// ------------------------------------------------------------------ //

test.describe('ShareResumeModal — revoke link flow', () => {

  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page)
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')
    const shareCard = page.locator('article').filter({ hasText: 'Product Manager Resume' })
    await shareCard.getByRole('button', { name: 'Share' }).click()
    await expect(page.getByRole('heading', { name: 'Share Resume' })).toBeVisible()
  })

  test('clicking Revoke link shows confirmation dialog', async ({ page }) => {
    await page.getByText('Revoke link').click()

    await expect(page.getByText('Revoking this link will immediately break all shared URLs')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Revoke permanently' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible()
  })

  test('clicking Cancel in revoke dialog keeps the link', async ({ page }) => {
    await page.getByText('Revoke link').click()
    await expect(page.getByRole('button', { name: 'Revoke permanently' })).toBeVisible()

    await page.getByRole('button', { name: 'Cancel' }).click()

    await expect(page.getByText(RESUME_WITH_SHARE.share_url!)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Revoke permanently' })).not.toBeVisible()
  })

  test('clicking Revoke permanently calls DELETE /resumes/:id/share', async ({ page }) => {
    let revokeApiCalled = false
    page.on('request', (req) => {
      if (req.url().includes('/share') && req.method() === 'DELETE') {
        revokeApiCalled = true
      }
    })

    await page.getByText('Revoke link').click()
    await page.getByRole('button', { name: 'Revoke permanently' }).click()
    await page.waitForTimeout(500)

    expect(revokeApiCalled).toBe(true)
  })

  test('after revoke, modal switches back to Generate button', async ({ page }) => {
    await page.getByText('Revoke link').click()
    await page.getByRole('button', { name: 'Revoke permanently' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByRole('button', { name: 'Generate shareable link' })).toBeVisible()
  })

  test('after revoke, share URL is no longer shown', async ({ page }) => {
    await page.getByText('Revoke link').click()
    await page.getByRole('button', { name: 'Revoke permanently' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText(RESUME_WITH_SHARE.share_url!)).not.toBeVisible()
  })
})


// ------------------------------------------------------------------ //
//  ShareResumeModal — close behaviours                                //
// ------------------------------------------------------------------ //

test.describe('ShareResumeModal — close behaviours', () => {

  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page)
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')
    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    await noShareCard.getByRole('button', { name: 'Share' }).click()
    await expect(page.getByRole('heading', { name: 'Share Resume' })).toBeVisible()
  })

  test('modal closes on Escape key', async ({ page }) => {
    await page.keyboard.press('Escape')
    await expect(page.getByRole('heading', { name: 'Share Resume' })).not.toBeVisible()
  })

  test('modal closes on backdrop click', async ({ page }) => {
    await page.locator('.fixed.inset-0.z-50').click({ position: { x: 5, y: 5 } })
    await expect(page.getByRole('heading', { name: 'Share Resume' })).not.toBeVisible()
  })
})


// ------------------------------------------------------------------ //
//  Edit page — Share button in header                                 //
// ------------------------------------------------------------------ //

test.describe('Edit page — Share button in header', () => {

  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    // Only mock the specific resume — avoids multiple Share buttons from workspace sidebar
    await page.route((url) => {
      const path = url.pathname
      return path.startsWith('/resumes') || path.startsWith('/jobs')
    }, async (route: Route) => {
      const url = new URL(route.request().url())
      const path = url.pathname
      const method = route.request().method()

      const getResumeMatch = path.match(/^\/resumes\/([0-9a-f-]{36})$/)
      if (getResumeMatch && method === 'GET') {
        const resume = [RESUME_NO_SHARE, RESUME_WITH_SHARE].find((r) => r.id === getResumeMatch[1])
        if (resume) {
          return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resume) })
        }
        return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not found' }) })
      }

      const shareMatch = path.match(/^\/resumes\/([0-9a-f-]{36})\/share$/)
      if (shareMatch && method === 'POST') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SHARE_LINK_RESPONSE) })
      }
      if (shareMatch && method === 'DELETE') {
        return route.fulfill({ status: 204 })
      }

      if (path === '/jobs' && method === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ jobs: [] }) })
      }

      // For resumes list (if edit page calls it), return empty
      if ((path === '/resumes/' || path === '/resumes') && method === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resumes: [], total: 0, page: 1, limit: 20, pages: 0 }) })
      }

      return route.continue()
    })
    await mockEditPageJobs(page)
  })

  test('edit page has a Share button in header', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_NO_SHARE.id}/edit`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('button', { name: 'Share' }).first()).toBeVisible()
  })

  test('Share button on edit page (no token) is not highlighted sky blue', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_NO_SHARE.id}/edit`)
    await page.waitForLoadState('networkidle')

    const shareBtn = page.getByRole('button', { name: 'Share' }).first()
    await expect(shareBtn).toBeVisible()
    const cls = await shareBtn.getAttribute('class') ?? ''
    expect(cls).not.toMatch(/text-sky/)
  })

  test('Share button on edit page (with token) is highlighted sky blue', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_WITH_SHARE.id}/edit`)
    await page.waitForLoadState('networkidle')

    const shareBtn = page.getByRole('button', { name: 'Share' }).first()
    await expect(shareBtn).toBeVisible()
    await expect(shareBtn).toHaveClass(/text-sky/)
  })

  test('clicking Share on edit page opens ShareResumeModal', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_NO_SHARE.id}/edit`)
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: 'Share' }).first().click()
    await expect(page.getByRole('heading', { name: 'Share Resume' })).toBeVisible()
  })

  test('edit page does not crash on load', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.goto(`/workspace/${RESUME_NO_SHARE.id}/edit`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    expect(errors).toEqual([])
  })
})


// ------------------------------------------------------------------ //
//  Public share page /r/[token]                                       //
// ------------------------------------------------------------------ //

test.describe('Public share page /r/[token]', () => {

  test('loading state shows spinner', async ({ page }) => {
    await page.route(`**/share/${RESUME_WITH_SHARE.share_token}`, async (route) => {
      await new Promise((r) => setTimeout(r, 1000))
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARED_RESUME_RESPONSE),
      })
    })

    await page.goto(`/r/${RESUME_WITH_SHARE.share_token}`)
    await expect(page.getByText('Loading resume')).toBeVisible()
  })

  test('valid token shows resume title and PDF iframe', async ({ page }) => {
    await page.route(`**/share/${RESUME_WITH_SHARE.share_token}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARED_RESUME_RESPONSE),
      })
    )

    await page.goto(`/r/${RESUME_WITH_SHARE.share_token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Software Engineer Resume')).toBeVisible()
    await expect(page.locator('iframe')).toBeVisible()
  })

  test('valid token shows PDF iframe with correct src', async ({ page }) => {
    await page.route(`**/share/${RESUME_WITH_SHARE.share_token}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARED_RESUME_RESPONSE),
      })
    )

    await page.goto(`/r/${RESUME_WITH_SHARE.share_token}`)
    await page.waitForLoadState('networkidle')

    const src = await page.locator('iframe').getAttribute('src')
    expect(src).toBe(SHARED_RESUME_RESPONSE.pdf_url)
  })

  test('valid token page shows View only header', async ({ page }) => {
    await page.route(`**/share/${RESUME_WITH_SHARE.share_token}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARED_RESUME_RESPONSE),
      })
    )

    await page.goto(`/r/${RESUME_WITH_SHARE.share_token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/View only/)).toBeVisible()
  })

  test('invalid token shows Link unavailable error', async ({ page }) => {
    await page.route('**/share/totally_invalid_token_xyz', (route) =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not found or revoked' }),
      })
    )

    await page.goto('/r/totally_invalid_token_xyz')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('heading', { name: 'Link unavailable' })).toBeVisible()
  })

  test('invalid token shows error message about revocation', async ({ page }) => {
    await page.route('**/share/revoked_token_111', (route) =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not found or revoked' }),
      })
    )

    await page.goto('/r/revoked_token_111')
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/revoked or does not exist/i)).toBeVisible()
  })

  test('no PDF error shows Link unavailable page', async ({ page }) => {
    // API returns 404 (which triggers the "revoked" branch in the frontend error handler)
    await page.route('**/share/no_pdf_token_222', (route) =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Resume has not been compiled yet.' }),
      })
    )

    await page.goto('/r/no_pdf_token_222')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('heading', { name: 'Link unavailable' })).toBeVisible()
    // 404 responses always show the generic revoked message
    await expect(page.getByText(/revoked or does not exist/i)).toBeVisible()
  })

  test('error page has Go to Latexy link', async ({ page }) => {
    await page.route('**/share/bad_token_000', (route) =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not found' }),
      })
    )

    await page.goto('/r/bad_token_000')
    await page.waitForLoadState('networkidle')

    const link = page.getByRole('link', { name: 'Go to Latexy' })
    await expect(link).toBeVisible()
    expect(await link.getAttribute('href')).toBe('/')
  })

  test('public page does not require authentication', async ({ page }) => {
    // No auth mocked — page should still work
    await page.route(`**/share/${RESUME_WITH_SHARE.share_token}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARED_RESUME_RESPONSE),
      })
    )

    await page.goto(`/r/${RESUME_WITH_SHARE.share_token}`)
    await page.waitForLoadState('networkidle')

    // Should show the resume, not a login redirect
    await expect(page.getByText('Software Engineer Resume')).toBeVisible()
  })

  test('public page does not crash', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.route(`**/share/${RESUME_WITH_SHARE.share_token}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARED_RESUME_RESPONSE),
      })
    )

    await page.goto(`/r/${RESUME_WITH_SHARE.share_token}`)
    await page.waitForLoadState('networkidle')

    expect(errors).toEqual([])
  })
})


// ------------------------------------------------------------------ //
//  API route verification — share endpoints                           //
// ------------------------------------------------------------------ //

test.describe('API route verification — share endpoints', () => {

  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page)
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')
  })

  test('generate link calls POST /resumes/:id/share', async ({ page }) => {
    const apiCalls: { method: string; url: string }[] = []

    page.on('request', (req) => {
      if (req.url().includes('/share')) {
        apiCalls.push({ method: req.method(), url: req.url() })
      }
    })

    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    await noShareCard.getByRole('button', { name: 'Share' }).click()
    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await page.waitForTimeout(500)

    const shareCall = apiCalls.find(
      (c) => c.method === 'POST' && c.url.includes(RESUME_NO_SHARE.id) && c.url.endsWith('/share')
    )
    expect(shareCall).toBeTruthy()
  })

  test('revoke link calls DELETE /resumes/:id/share', async ({ page }) => {
    const apiCalls: { method: string; url: string }[] = []

    page.on('request', (req) => {
      if (req.url().includes('/share')) {
        apiCalls.push({ method: req.method(), url: req.url() })
      }
    })

    const shareCard = page.locator('article').filter({ hasText: 'Product Manager Resume' })
    await shareCard.getByRole('button', { name: 'Share' }).click()
    await page.getByText('Revoke link').click()
    await page.getByRole('button', { name: 'Revoke permanently' }).click()
    await page.waitForTimeout(500)

    const revokeCall = apiCalls.find(
      (c) =>
        c.method === 'DELETE' &&
        c.url.includes(RESUME_WITH_SHARE.id) &&
        c.url.endsWith('/share')
    )
    expect(revokeCall).toBeTruthy()
  })

  test('public share page calls GET /share/:token', async ({ page }) => {
    const apiCalls: string[] = []

    await page.route(`**/share/${RESUME_WITH_SHARE.share_token}`, (route) => {
      apiCalls.push(route.request().url())
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SHARED_RESUME_RESPONSE),
      })
    })

    await page.goto(`/r/${RESUME_WITH_SHARE.share_token}`)
    await page.waitForLoadState('networkidle')

    expect(apiCalls.some((u) => u.includes(`/share/${RESUME_WITH_SHARE.share_token}`))).toBe(true)
  })

  test('share link URL contains token', async ({ page }) => {
    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    await noShareCard.getByRole('button', { name: 'Share' }).click()
    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText(SHARE_LINK_RESPONSE.share_token)).toBeVisible()
  })

  test('share link URL contains /r/ path', async ({ page }) => {
    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    await noShareCard.getByRole('button', { name: 'Share' }).click()
    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText(/\/r\//)).toBeVisible()
  })
})


// ------------------------------------------------------------------ //
//  Resume list — share_token state reflected in card                  //
// ------------------------------------------------------------------ //

test.describe('Resume list — share_token reflected in card state', () => {

  test('workspace shows active Share button for resumes with existing token', async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page, [RESUME_WITH_SHARE])
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')

    const shareBtn = page.getByRole('button', { name: 'Share' }).first()
    await expect(shareBtn).toBeVisible()
    await expect(shareBtn).toHaveClass(/text-sky/)
  })

  test('after generating link, modal shows the new share URL', async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page, [RESUME_NO_SHARE])
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')

    const noShareCard = page.locator('article').filter({ hasText: 'Software Engineer Resume' })
    await noShareCard.getByRole('button', { name: 'Share' }).click()
    await page.getByRole('button', { name: 'Generate shareable link' }).click()
    await page.waitForTimeout(500)

    // The modal should show the new share URL (confirming state was updated)
    await expect(page.getByText(SHARE_LINK_RESPONSE.share_url)).toBeVisible()
  })
})
