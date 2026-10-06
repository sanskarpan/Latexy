import { expect, test } from '@playwright/test'

const RESUME_ID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeef'

test('drops deferred parent and academic metadata from the previous account', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'metadata ownership proof runs against the production editor bundle')

  let owner = 'owner-a'
  let sessionCalls = 0
  let parentRequests = 0
  let reportRequests = 0
  let oldParentFinished = false
  let oldReportFinished = false
  let releaseOldParent!: () => void
  let releaseOldReport!: () => void
  const oldParent = new Promise<void>((resolve) => { releaseOldParent = resolve })
  const oldReport = new Promise<void>((resolve) => { releaseOldReport = resolve })

  await page.route('**/api/auth/get-session', (route) => {
    sessionCalls += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { token: `token-${owner}` },
        user: { id: owner, email: `${owner}@example.com`, name: owner },
      }),
    })
  })
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: owner,
      title: 'Metadata ownership fixture',
      latex_content: '\\documentclass{article}\\begin{document}Metadata fixture.\\end{document}',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      document_type: 'academic_cv',
      content_source: 'builder_variant',
      parent_resume_id: owner === 'owner-a' ? 'parent-a' : 'parent-b',
      metadata: {},
    }),
  }))
  await page.route((url) => url.pathname === '/resumes/parent-a', async (route) => {
    parentRequests += 1
    await oldParent
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ title: 'Old account parent' }) })
    oldParentFinished = true
  })
  await page.route((url) => url.pathname === '/resumes/parent-b', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ title: 'New account parent' }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/academic-cv-report`, async (route) => {
    reportRequests += 1
    if (reportRequests === 1) {
      await oldReport
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ is_academic_cv: true, detected_sections: ['old account signal'], estimated_pages: 2, confidence: 0.81 }),
      })
      oldReportFinished = true
      return
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ is_academic_cv: true, detected_sections: ['new account signal'], estimated_pages: 4, confidence: 0.94 }),
    })
  })
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname.includes('/checkpoints') || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (route) => route.abort())

  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
  await expect.poll(() => parentRequests).toBeGreaterThan(0)
  await expect.poll(() => reportRequests).toBeGreaterThan(0)
  const sameDocumentUrl = page.url()
  await page.evaluate(() => {
    ;(window as Window & { __metadataOwnershipMarker?: number }).__metadataOwnershipMarker = 1
  })

  owner = 'owner-b'
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(() => sessionCalls).toBeGreaterThan(1)
  await expect(page.getByText('New account parent', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/Academic CV detected \(4 pages, new account signal\)/)).toBeVisible({ timeout: 15_000 })

  const oldParentResponse = page.waitForResponse((response) => response.url().endsWith(`/resumes/parent-a`) && response.status() === 200)
  const oldReportResponse = page.waitForResponse((response) => response.url().endsWith(`/resumes/${RESUME_ID}/academic-cv-report`) && response.status() === 200)
  releaseOldParent()
  releaseOldReport()
  const [parentResponse, reportResponse] = await Promise.all([oldParentResponse, oldReportResponse])
  await Promise.all([parentResponse.finished(), reportResponse.finished()])
  await expect.poll(() => oldParentFinished).toBe(true)
  await expect.poll(() => oldReportFinished).toBe(true)
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
  }))
  await expect(page.getByText('Old account parent', { exact: true })).toHaveCount(0)
  await expect(page.getByText(/Academic CV detected \(2 pages, old account signal\)/)).toHaveCount(0)
  expect(page.url()).toBe(sameDocumentUrl)
  expect(await page.evaluate(() => (window as Window & { __metadataOwnershipMarker?: number }).__metadataOwnershipMarker)).toBe(1)
})

test('does not clear the new parent link when the previous account parent fails', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'metadata ownership proof runs against the production editor bundle')

  let owner = 'owner-a'
  let sessionCalls = 0
  let releaseOldParent!: () => void
  let parentStarted = false
  let oldParentFinished = false
  const oldParent = new Promise<void>((resolve) => { releaseOldParent = resolve })

  await page.route('**/api/auth/get-session', (route) => {
    sessionCalls += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session: { token: `token-${owner}` }, user: { id: owner, email: `${owner}@example.com`, name: owner } }),
    })
  })
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: owner,
      title: 'Parent failure fixture',
      latex_content: '\\documentclass{article}\\begin{document}Parent failure fixture.\\end{document}',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      document_type: 'resume',
      content_source: 'builder_variant',
      parent_resume_id: owner === 'owner-a' ? 'parent-a' : 'parent-b',
      metadata: {},
    }),
  }))
  await page.route((url) => url.pathname === '/resumes/parent-a', async (route) => {
    parentStarted = true
    await oldParent
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'deleted' }) })
    oldParentFinished = true
  })
  await page.route((url) => url.pathname === '/resumes/parent-b', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ title: 'New account parent' }),
  }))
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname.includes('/checkpoints') || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (route) => route.abort())

  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
  await expect.poll(() => sessionCalls).toBeGreaterThan(0)
  await expect.poll(() => parentStarted).toBe(true)
  owner = 'owner-b'
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(() => sessionCalls).toBeGreaterThan(1)
  await expect(page.getByText('New account parent', { exact: true })).toBeVisible({ timeout: 15_000 })

  const oldParentResponse = page.waitForResponse((response) => response.url().endsWith(`/resumes/parent-a`) && response.status() === 404)
  releaseOldParent()
  const parentResponse = await oldParentResponse
  await parentResponse.finished()
  await expect.poll(() => oldParentFinished).toBe(true)
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
  }))
  await expect(page.getByText('New account parent', { exact: true })).toBeVisible()
})
