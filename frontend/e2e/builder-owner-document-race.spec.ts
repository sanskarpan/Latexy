import { expect, test, type Page } from '@playwright/test'

const RESUME_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const TEMPLATE_A = '11111111-1111-1111-1111-111111111111'
const TEMPLATE_B = '22222222-2222-2222-2222-222222222222'

const STRUCTURED = {
  basics: { name: 'Builder User', label: 'Engineer', email: 'builder@example.com', phone: '', location: '', website: '', linkedin: '', github: '', summary: 'Builder summary' },
  experience: [], education: [], projects: [], skills: [], certifications: [], awards: [], languages: [], interests: [],
  section_order: ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests'],
  hidden_sections: [],
}

function builderResponse(owner: string, id = RESUME_A, status: 'active' | 'detached' = 'active') {
  return {
    resume: {
      id, user_id: owner, title: `${owner === 'owner-a' ? 'Owner A' : 'Owner B'} builder`,
      latex_content: '\\documentclass{article}\\begin{document}Builder\\end{document}',
      is_template: false, parent_resume_id: null, variant_count: 0,
      selected_template_id: owner === 'owner-a' ? TEMPLATE_A : TEMPLATE_B,
      content_source: 'builder', builder_status: status, structured_content: STRUCTURED,
      structured_version: 1, created_at: '2026-05-29T00:00:00Z', updated_at: '2026-05-29T00:00:00Z',
      document_type: 'resume', metadata: {},
    },
    metrics: { completeness_score: 84, page_estimate: 1, warnings: [], missing_sections: [] },
    preview: { template_family: owner === 'owner-a' ? 'ats' : 'executive', sections: [] },
    template_family: owner === 'owner-a' ? 'ats' : 'executive',
  }
}

function templates(owner: string) {
  return [
    { id: TEMPLATE_A, name: `${owner} template`, description: 'Test template', category: 'ats_safe', category_label: 'ATS-Safe', sort_order: 0, thumbnail_url: null, pdf_url: null, template_family: 'ats' },
    { id: TEMPLATE_B, name: `${owner} executive template`, description: 'Test template', category: 'executive', category_label: 'Executive', sort_order: 1, thumbnail_url: null, pdf_url: null, template_family: 'executive' },
  ]
}

async function switchOwner(page: Page, owner: { value: string }, nextOwner: string) {
  owner.value = nextOwner
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test-owner-switch' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
}

function installDynamicSession(page: Page, owner: { value: string }, onResponse?: (currentOwner: string) => void) {
  return page.route('**/api/auth/get-session', route => {
    const currentOwner = owner.value
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: `session-${currentOwner}`, userId: currentOwner, token: `token-${currentOwner}`, expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: currentOwner, email: `${currentOwner}@example.com`, name: currentOwner },
      }),
    }).then(() => onResponse?.(currentOwner))
  })
}

test.describe('builder owner/document transition controls', () => {
  test('ignores a deferred A save across same-document A→B→A owner ABA', async ({ page }) => {
    const owner = { value: 'owner-a' }
    let sessionCalls = 0
    let saveStarted = false
    let saveFinished = false
    let saveResponseFinished = false
    let releaseSave!: () => void
    const saveGate = new Promise<void>(resolve => { releaseSave = resolve })

    await installDynamicSession(page, owner, () => { sessionCalls += 1 })
    await page.route('**/ws/**', route => route.abort())
    page.on('response', response => {
      if (response.url().includes(`/resumes/${RESUME_A}/builder`) && response.request().method() === 'PATCH' && response.status() === 200) {
        saveResponseFinished = true
      }
    })
    await page.route('**/resumes/builder/templates', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(templates(owner.value)) }))
    await page.route(`**/resumes/${RESUME_A}/builder`, async route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse(owner.value, RESUME_A)) })
      }
      if (route.request().method() === 'PATCH') {
        saveStarted = true
        await saveGate
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse('owner-a', RESUME_A, 'detached')) })
        saveFinished = true
        return
      }
      return route.fallback()
    })

    await page.goto(`/workspace/builder/${RESUME_A}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Owner A builder' })).toBeVisible()
    await page.locator('#builder-resume-title').fill('Owner A deferred document save')
    await expect.poll(() => saveStarted).toBe(true)

    await switchOwner(page, owner, 'owner-b')
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await expect(page.getByRole('heading', { name: 'Owner B builder' })).toBeVisible()
    await expect(page.getByRole('option', { name: 'owner-b executive template · Executive', exact: true })).toBeAttached()

    await switchOwner(page, owner, 'owner-a')
    await expect.poll(() => sessionCalls).toBeGreaterThan(2)
    await expect(page.getByRole('heading', { name: 'Owner A builder' })).toBeVisible()
    await expect(page.getByRole('option', { name: 'owner-a template · ATS-Safe', exact: true })).toBeAttached()

    try {
      releaseSave()
      await expect.poll(() => saveFinished).toBe(true)
      await expect.poll(() => saveResponseFinished).toBe(true)
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))))
      await expect(page.getByRole('heading', { name: 'Owner A builder' })).toBeVisible()
      await expect(page.getByText('Builder detached')).not.toBeVisible()
    } finally {
      releaseSave()
    }
  })

  test('does not hydrate owner B with deferred owner-A seed upload', async ({ page }) => {
    const owner = { value: 'owner-a' }
    let sessionCalls = 0
    let seedStarted = false
    let seedFinished = false
    let releaseSeed!: () => void
    const seedGate = new Promise<void>(resolve => { releaseSeed = resolve })

    await installDynamicSession(page, owner, () => { sessionCalls += 1 })
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(templates(owner.value)) }))
    await page.route('**/resumes/builder/seed-upload', async route => {
      seedStarted = true
      await seedGate
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          filename: 'resume.json',
          format: 'json_resume_v1',
          structured_content: { ...STRUCTURED, basics: { ...STRUCTURED.basics, name: 'Owner A imported' } },
          metrics: { completeness_score: 82, page_estimate: 1, warnings: [], missing_sections: [] },
          interchange_warnings: [],
        }),
      })
      seedFinished = true
    })

    await page.goto('/workspace/builder/new', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Create your résumé' })).toBeVisible()
    await page.locator('input[type="file"]').setInputFiles({ name: 'resume.json', mimeType: 'application/json', buffer: Buffer.from('{"resume":"seed"}') })
    await expect.poll(() => seedStarted).toBe(true)

    await switchOwner(page, owner, 'owner-b')
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await expect(page.getByRole('heading', { name: 'Create your résumé' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'owner-b template', level: 3, exact: true })).toBeVisible()
    await expect(page.getByText('No name imported yet', { exact: true })).toBeVisible()

    const seedResponse = page.waitForResponse(response =>
      response.url().includes('/resumes/builder/seed-upload')
      && response.request().method() === 'POST'
      && response.status() === 200)
    try {
      releaseSeed()
      await expect.poll(() => seedFinished).toBe(true)
      await (await seedResponse).finished()
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))))
      await expect(page.getByText('Owner A imported')).not.toBeVisible()
      await expect(page.getByText('No name imported yet', { exact: true })).toBeVisible()
    } finally {
      releaseSeed()
    }
  })

  test('same-owner seed upload still hydrates the current builder', async ({ page }) => {
    let seedCalls = 0
    await page.route('**/api/auth/get-session', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'session-owner-a', userId: 'owner-a', token: 'token-owner-a', expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: 'owner-a', email: 'owner-a@example.com', name: 'Owner A' },
      }),
    }))
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(templates('owner-a')) }))
    await page.route('**/resumes/builder/seed-upload', route => {
      seedCalls += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        success: true, filename: 'resume.json', format: 'json_resume_v1',
        structured_content: { ...STRUCTURED, basics: { ...STRUCTURED.basics, name: 'Owner A imported' } },
        metrics: { completeness_score: 82, page_estimate: 1, warnings: [], missing_sections: [] }, interchange_warnings: [],
      }) })
    })
    await page.goto('/workspace/builder/new', { waitUntil: 'domcontentloaded' })
    await page.locator('input[type="file"]').setInputFiles({ name: 'resume.json', mimeType: 'application/json', buffer: Buffer.from('{"resume":"seed"}') })
    await expect(page.getByText('Owner A imported')).toBeVisible()
    expect(seedCalls).toBe(1)
  })
})
