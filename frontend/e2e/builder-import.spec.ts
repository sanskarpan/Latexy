import { expect, test, type Page } from '@playwright/test'

async function mockWorkspaceSupport(page: Page) {
  await page.route('**/ws/**', (route) => route.abort())
  await page.route((url) => {
    return url.pathname.startsWith('/templates') || url.pathname === '/tenants/current-context'
  }, async (route) => {
    const url = new URL(route.request().url())

    if (url.pathname === '/tenants/current-context') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tenant: null }),
      })
    }

    if (url.pathname === '/templates/categories') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    }

    if (url.pathname === '/templates/' || url.pathname === '/templates') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    }

    return route.continue()
  })
}

async function openBuilderMode(page: Page) {
  await mockWorkspaceSupport(page)
  await page.goto('/workspace/new', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('No templates found')).toBeVisible()
  await page.locator('input[placeholder*="Q3 2026"]').fill('Builder Import Resume')
  await page.locator('button').filter({ hasText: 'Import from Builder' }).last().click({ force: true })
  await expect(page.getByText('Which resume builder are you importing from?')).toBeVisible()
}

test.describe('Builder Import Wizard', () => {
  test('converts a builder export and enables resume creation', async ({ page }) => {
    await page.route('**/formats/parse', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          format: 'json',
          filename: 'kickresume-export.json',
          name: 'Avery Stone',
          email: 'avery@example.com',
          experience_count: 3,
          education_count: 1,
          skills: ['Python', 'FastAPI', 'PostgreSQL'],
          has_summary: true,
        }),
      })
    })

    await page.route('**/formats/upload**', async (route) => {
      const url = new URL(route.request().url())
      expect(url.searchParams.get('source_platform')).toBe('kickresume')

      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          format: 'json',
          filename: 'kickresume-export.json',
          is_direct: true,
          latex_content: '\\documentclass{article}\\begin{document}Imported builder resume\\end{document}',
        }),
      })
    })

    await openBuilderMode(page)
    await page.locator('button[type="button"]').filter({ hasText: 'Kickresume' }).last().click()
    await page.getByRole('button', { name: 'Next' }).click()
    await expect(page.getByText('How to export from Kickresume')).toBeVisible()
    await page.getByRole('button', { name: 'Next' }).click()

    await page.locator('input[type="file"]').setInputFiles({
      name: 'kickresume-export.json',
      mimeType: 'application/json',
      buffer: Buffer.from('{"basics":{"name":"Avery Stone"}}'),
    })

    await expect(page.getByText('Parsed preview')).toBeVisible()
    await expect(page.getByText('Avery Stone')).toBeVisible()
    await page.getByRole('button', { name: /Convert to LaTeX/i }).click()

    await expect(page.getByText(/Resume imported/)).toBeVisible()
    const createButton = page.getByRole('button', { name: 'Create Resume' })
    await expect(createButton).toBeVisible()
    await expect(createButton).toBeEnabled()
  })

  test('generic builder imports omit the source_platform query parameter', async ({ page }) => {
    await page.route('**/formats/parse', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          format: 'pdf',
          filename: 'generic-builder.pdf',
          name: 'Taylor Finch',
          email: 'taylor@example.com',
          experience_count: 2,
          education_count: 1,
          skills: ['Writing', 'Research'],
          has_summary: false,
        }),
      })
    })

    await page.route('**/formats/upload**', async (route) => {
      const url = new URL(route.request().url())
      expect(url.searchParams.has('source_platform')).toBeFalsy()

      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          format: 'pdf',
          filename: 'generic-builder.pdf',
          is_direct: true,
          latex_content: '\\documentclass{article}\\begin{document}Generic builder import\\end{document}',
        }),
      })
    })

    await openBuilderMode(page)
    await page.locator('button[type="button"]').filter({ hasText: 'Generic JSON / Other' }).last().click()
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Next' }).click()

    await page.locator('input[type="file"]').setInputFiles({
      name: 'generic-builder.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 mock'),
    })

    await expect(page.getByText('Taylor Finch')).toBeVisible()
    await page.getByRole('button', { name: /Convert to LaTeX/i }).click()
    await expect(page.getByRole('button', { name: 'Create Resume' })).toBeVisible()
  })
})
