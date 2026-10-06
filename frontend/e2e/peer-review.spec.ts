import { expect, test, type Page } from '@playwright/test'

const TOKEN = 'peer-review-token-123'
const SHARED = {
  resume_title: 'Peer review resume',
  share_token: TOKEN,
  pdf_url: 'https://cdn.example.test/resume.pdf',
  compiled_at: '2026-09-14T00:00:00Z',
  accessible_text: 'Experience\nBuilt safe systems',
  is_anonymous: false,
  anonymous_processing: false,
  review_comments: true,
}

const COMMENT = {
  id: 'comment-1',
  reviewer_label: 'Reviewer ABC123',
  content: '<script>window.__reviewXss = true</script>',
  line_number: 2,
  section_tag: 'Experience',
  page_number: 1,
  x: 0.25,
  y: 0.2,
  resolved: false,
  created_at: '2026-09-14T00:00:00Z',
  updated_at: '2026-09-14T00:00:00Z',
}

async function mockReviewApi(page: Page, reviewEnabled = true) {
  let comments = [COMMENT]
  let revoked = false
  await page.route((url: URL) => url.pathname.startsWith(`/share/${TOKEN}`), async (route) => {
    const { pathname } = new URL(route.request().url())
    if (pathname === `/share/${TOKEN}` && route.request().method() === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...SHARED, review_comments: reviewEnabled }) })
    }
    if (pathname === `/share/${TOKEN}/review-comments`) {
      if (revoked) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'revoked' }) })
      if (route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(comments) })
      const body = route.request().postDataJSON()
      const created = { ...COMMENT, id: `comment-${comments.length + 1}`, content: body.content, line_number: body.line_number ?? null, section_tag: body.section_tag ?? null }
      comments = [...comments, created]
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(created) })
    }
    return route.continue()
  })
  // Keep the PDF renderer real while making the external signed URL
  // deterministic and offline for this browser test.
  await page.route('https://cdn.example.test/resume.pdf', async (route) => {
    const pdf = '%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n5 0 obj\n<< /Length 44 >>\nstream\nBT /F1 18 Tf 72 720 Td (Latexy review) Tj ET\nendstream\nendobj\nxref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000241 00000 n \n0000000311 00000 n \ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n405\n%%EOF\n'
    return route.fulfill({ status: 200, contentType: 'application/pdf', body: Buffer.from(pdf) })
  })
  return { revoke: () => { revoked = true } }
}

test.describe('public peer review', () => {
  test('loads capability-gated comments, renders script text inert, and creates a comment', async ({ page }) => {
    await mockReviewApi(page)
    await page.goto(`/r/${TOKEN}`)
    await expect(page.getByRole('heading', { name: 'Review comments' })).toBeVisible()
    await expect(page.getByTestId('review-comment').getByText('<script>window.__reviewXss = true</script>', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => (window as Window & { __reviewXss?: boolean }).__reviewXss)).toBeUndefined()

    const pdfPage = page.getByTestId('review-pdf-page').first()
    await expect(pdfPage).toBeVisible()
    await pdfPage.click({ position: { x: 100, y: 100 } })
    await expect(page.getByTestId('review-selected-anchor')).toBeVisible()
    await page.getByLabel('Leave feedback').fill('Please add one more quantified outcome.')
    await page.getByLabel('Legacy source line (optional; not linked to the document)').fill('2')
    await page.getByRole('button', { name: 'Post review comment' }).click()
    await expect(page.getByRole('paragraph').filter({ hasText: 'Please add one more quantified outcome.' })).toBeVisible()
    await expect(page.getByTestId('review-comment-marker')).toHaveCount(2)
  })

  test('shows a clear revoked error for review operations', async ({ page }) => {
    const control = await mockReviewApi(page)
    control.revoke()
    await page.goto(`/r/${TOKEN}`)
    await expect(page.getByText('This review link has been revoked.', { exact: true })).toBeVisible()
  })

  test('does not fetch or render a public review panel when capability is disabled', async ({ page }) => {
    let reviewFetches = 0
    await mockReviewApi(page, false)
    await page.on('request', (request) => {
      if (request.url().includes('/review-comments')) reviewFetches += 1
    })
    await page.goto(`/r/${TOKEN}`)
    await expect(page.getByRole('heading', { name: 'Review comments' })).not.toBeVisible()
    expect(reviewFetches).toBe(0)
  })
})
