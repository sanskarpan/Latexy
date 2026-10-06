import { expect, test } from '@playwright/test'

test('builder import renders source-aware validation details', async ({ page }) => {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { id: 'session-1', userId: 'user-1', token: 'token-1' },
      user: { id: 'user-1', email: 'user@example.com', name: 'Taylor' },
    }),
  }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"tenant":null}',
  }))
  await page.route((url) => ['/config/feature-flags', '/config/entitlements'].includes(url.pathname), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/resumes/builder/templates', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'template-1', name: 'Minimal', description: 'Builder template', category: 'minimal',
      category_label: 'Minimal', sort_order: 1, thumbnail_url: null, pdf_url: null,
      template_family: 'minimal',
    }]),
  }))
  await page.route((url) => url.pathname === '/resumes/builder/seed-upload', (route) => route.fulfill({
    status: 422,
    contentType: 'application/json',
    body: JSON.stringify({
      error: {
        code: 'resume_validation_error',
        message: 'Resume data failed validation.',
        details: {
          issues: [{
            path: 'work[0].startDate',
            message: "JSON Resume field 'work[0].startDate' must use YYYY, YYYY-MM, or YYYY-MM-DD",
            line: 7,
            column: 7,
          }],
        },
      },
    }),
  }))

  await page.goto('/workspace/builder/new')
  await page.locator('input[type="file"]').setInputFiles({
    name: 'invalid.json',
    mimeType: 'application/json',
    buffer: Buffer.from('{"work":[{"startDate":"April 2024"}]}'),
  })

  const alert = page.locator('[role="alert"]').filter({ hasText: 'Import validation failed' })
  await expect(alert).toContainText('Import validation failed')
  await expect(alert).toContainText('work[0].startDate')
  await expect(alert).toContainText('line 7, column 7')
  await expect(alert).toContainText('must use YYYY')
})
