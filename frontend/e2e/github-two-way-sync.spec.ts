import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = '123e4567-e89b-42d3-a456-426614174032'
const LOCAL_LATEX = [
  '\\documentclass{article}',
  '\\begin{document}',
  'Local resume source with enough content to initialize the editor and compilation preview.',
  '\\end{document}',
].join('\n')
const REMOTE_LATEX = LOCAL_LATEX.replace('Local resume source', 'Remote GitHub source')

async function mockEditor(page: Page, privateSync: boolean) {
  await page.route('**/api/auth/get-session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { token: 'github-sync-token' },
      user: { id: 'sync-user', email: 'sync@example.com', name: 'Sync User' },
    }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, route => {
    if (route.request().method() === 'PUT') return route.fallback()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: RESUME_ID,
        user_id: 'sync-user',
        title: 'Git Resume',
        latex_content: LOCAL_LATEX,
        document_type: 'resume',
        github_sync_enabled: true,
        github_repo_name: 'latexy-resumes',
        metadata: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      }),
    })
  })
  await page.route('**/github/status', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      connected: true,
      username: 'octocat',
      public_import: true,
      private_sync: privateSync,
    }),
  }))
  await page.route('**/dropbox/status', route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"connected":false}',
  }))
  await page.route((url) => url.pathname.includes('/checkpoints'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '[]',
  }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{"is_academic_cv":false,"detected_sections":[],"estimated_pages":1,"confidence":0}',
  }))
  await page.route((url) => url.pathname === '/ats/quick-score', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{"score":70,"grade":"C","sections_found":[],"missing_sections":[]}',
  }))
  await page.route((url) => url.pathname === '/jobs/submit', route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"success":false,"message":"preview skipped"}',
  }))
  await page.route((url) => url.pathname.startsWith('/analytics'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{}',
  }))
  await page.route('**/ws/**', route => route.abort())
}

test('private GitHub sync saves before push and applies a confirmed persistent pull', async ({ page }) => {
  await mockEditor(page, true)
  const operations: string[] = []
  let updateCalls = 0

  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, async route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    updateCalls += 1
    operations.push('save')
    expect(route.request().postDataJSON()).toMatchObject({
      title: 'Git Resume',
      latex_content: LOCAL_LATEX,
    })
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
  await page.route((url) => url.pathname.endsWith(`/github/resumes/${RESUME_ID}/push`), route => {
    operations.push('push')
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{"success":true,"message":"Pushed safely","commit_url":"https://github.com/octocat/latexy-resumes/commit/1"}',
    })
  })
  await page.route((url) => url.pathname.endsWith(`/github/resumes/${RESUME_ID}/pull`), route => {
    operations.push('pull')
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, latex_content: REMOTE_LATEX }),
    })
  })

  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: 'Push' })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Push' }).click()
  await expect(page.getByText('Pushed safely')).toBeVisible()
  expect(operations.slice(0, 2)).toEqual(['save', 'push'])

  await page.getByRole('button', { name: 'Pull' }).click()
  await expect(page.getByRole('alertdialog')).toContainText('Unsaved changes will be overwritten')
  await page.getByRole('button', { name: 'Replace' }).click()
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
  ).__latexyMonacoEditor?.getValue())).toContain('Remote GitHub source')
  await page.waitForTimeout(2800)
  expect(updateCalls).toBe(1)
})

test('an import-only GitHub grant does not expose unusable private-sync controls', async ({ page }) => {
  await mockEditor(page, false)
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: 'Ask AI' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: 'Sync', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Push' })).toHaveCount(0)
})
