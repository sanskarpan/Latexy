import { expect, test, type Page } from '@playwright/test'

const ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const TEMPLATE = '11111111-1111-1111-1111-111111111111'
const CAPABILITIES = '**/resumes/builder/capabilities'
const BUILDER = `**/resumes/${ID}/builder/v1`
const structured = {
  basics: { name: 'Synthetic Candidate', label: 'Engineer', email: '', phone: '', location: '', website: '', linkedin: '', github: '', summary: '' },
  experience: [], education: [], projects: [], skills: [], certifications: [], awards: [], languages: [], interests: [],
  section_order: ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests'], hidden_sections: [],
}
function builder(status = 'active') {
  return {
    resume: {
      id: ID, user_id: 'builder-user', title: 'Saved builder', latex_content: '\\documentclass{article}\\begin{document}Synthetic Candidate\\end{document}',
      is_template: false, document_type: 'resume', selected_template_id: TEMPLATE, content_source: 'builder', builder_status: status,
      structured_content: structured, structured_version: 1, created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z',
    },
    template_family: 'minimal', metrics: { completeness_score: 10, page_estimate: 1, warnings: [], missing_sections: [] },
    preview: { template_family: 'minimal', sections: [] },
  }
}

async function setup(page: Page, status = 'active') {
  const calls = { templates: 0, reads: 0, writes: 0, legacyWrites: 0, compiles: 0, exports: 0 }
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: {
    session: { id: 'builder-session', userId: 'builder-user', token: 'synthetic-token', expiresAt: '2099-01-01T00:00:00Z' },
    user: { id: 'builder-user', email: 'builder@example.com', name: 'Builder User' },
  } }))
  await page.route('**/ws/**', route => route.abort())
  await page.route('**/resumes/builder/templates', route => {
    calls.templates += 1
    return route.fulfill({ json: [{ id: TEMPLATE, name: 'Minimal', description: '', category: 'minimal', category_label: 'Minimal', sort_order: 0, template_family: 'minimal' }] })
  })
  await page.route(BUILDER, route => {
    if (route.request().method() === 'GET') calls.reads += 1
    else calls.writes += 1
    const response = builder(status)
    if (route.request().method() === 'PATCH') {
      response.resume.title = route.request().postDataJSON().title ?? response.resume.title
      response.resume.structured_version += 1
    }
    return route.fulfill({ json: response })
  })
  await page.route('**/resumes/builder/v1', route => {
    calls.writes += 1
    return route.fulfill({ status: 201, json: builder() })
  })
  await page.route('**/resumes/builder/v1/seed-upload', route => {
    calls.writes += 1
    return route.fulfill({ status: 400, json: { detail: 'Not needed in this fixture' } })
  })
  await page.route(url => url.pathname === `/resumes/${ID}/builder` || url.pathname === '/resumes/builder' || url.pathname === '/resumes/builder/seed-upload', route => {
    if (route.request().method() !== 'GET') calls.legacyWrites += 1
    return route.fulfill({ json: builder() })
  })
  await page.route('**/jobs/submit', route => { calls.compiles += 1; return route.fulfill({ status: 500, json: {} }) })
  await page.route('**/export/**', route => { calls.exports += 1; return route.fulfill({ body: 'Synthetic export' }) })
  return calls
}

for (const scenario of [
  { name: 'old version', status: 200, body: { guided_builder_version: 0 } },
  { name: 'missing version', status: 200, body: {} },
  { name: 'unknown future version', status: 200, body: { guided_builder_version: 2 } },
  { name: 'missing route', status: 404, body: {} },
  { name: 'server failure', status: 503, body: {} },
]) {
  test(`blocks editable builder on ${scenario.name} and preserves source navigation`, async ({ page }) => {
    const calls = await setup(page)
    await page.route(CAPABILITIES, route => route.fulfill({ status: scenario.status, json: scenario.body }))
    await page.goto(`/workspace/builder/${ID}`)
    await expect(page.getByRole('heading', { name: 'Guided builder is unavailable' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Open Advanced Editor' })).toHaveAttribute('href', `/workspace/${ID}/edit`)
    await expect(page.getByRole('link', { name: 'Back to workspace' })).toHaveAttribute('href', '/workspace')
    await expect(page.locator('#builder-resume-title')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Preview PDF', exact: true })).toHaveCount(0)
    expect(calls).toEqual({ templates: 0, reads: 0, writes: 0, legacyWrites: 0, compiles: 0, exports: 0 })
  })
}

test('rechecks after backend upgrade on retry and page refresh', async ({ page }) => {
  const calls = await setup(page)
  let supported = false
  let checks = 0
  await page.route(CAPABILITIES, route => {
    checks += 1
    return route.fulfill({ status: supported ? 200 : 404, json: supported ? { guided_builder_version: 1 } : {} })
  })
  await page.goto('/workspace/builder/new')
  await expect(page.getByRole('heading', { name: 'Guided builder is unavailable' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Use source editor' })).toHaveAttribute('href', '/workspace/new')
  expect(calls.templates).toBe(0)
  supported = true
  await page.getByRole('button', { name: 'Retry compatibility check' }).click()
  await expect(page.locator('#new-builder-resume-title')).toBeVisible()
  const beforeRefresh = checks
  await page.reload()
  await expect(page.locator('#new-builder-resume-title')).toBeVisible()
  expect(checks).toBeGreaterThan(beforeRefresh)
})

test('blocks a downgraded autosave and preserves the unsaved draft across retry', async ({ page }) => {
  const calls = await setup(page)
  let supported = true
  await page.route(CAPABILITIES, route => route.fulfill({ json: { guided_builder_version: supported ? 1 : 0 } }))
  await page.goto(`/workspace/builder/${ID}`)
  await expect(page.locator('#builder-resume-title')).toBeVisible()
  supported = false
  await page.locator('#builder-resume-title').fill('Unsaved rollout draft')
  await expect(page.getByRole('heading', { name: 'Guided builder is unavailable' })).toBeVisible()
  await expect(page.locator('#builder-resume-title')).toBeHidden()
  expect(calls.writes).toBe(0)
  supported = true
  await page.getByRole('button', { name: 'Retry compatibility check' }).click()
  await expect(page.locator('#builder-resume-title')).toHaveValue('Unsaved rollout draft')
  await page.getByRole('button', { name: 'Save failed · Retry' }).click()
  await expect.poll(() => calls.writes).toBe(1)
  expect(calls.legacyWrites).toBe(0)
})

for (const action of ['create', 'import', 'preview', 'export', 'reattach']) {
  test(`rechecks compatibility before ${action}`, async ({ page }) => {
    const calls = await setup(page, action === 'reattach' ? 'detached' : 'active')
    let supported = true
    await page.route(CAPABILITIES, route => route.fulfill({ status: supported ? 200 : 503, json: { guided_builder_version: 1 } }))
    const isNew = action === 'create' || action === 'import'
    await page.goto(isNew ? '/workspace/builder/new' : `/workspace/builder/${ID}`)
    await expect(page.locator(isNew ? '#new-builder-resume-title' : '#builder-resume-title')).toBeVisible()
    supported = false
    if (action === 'create') {
      await page.locator('#new-builder-resume-title').fill('New draft')
      await page.getByRole('button', { name: 'Start my résumé', exact: true }).click()
    } else if (action === 'import') {
      await page.locator('input[type="file"]').setInputFiles({ name: 'resume.json', mimeType: 'application/json', buffer: Buffer.from('{"basics":{"name":"Synthetic"}}') })
    } else if (action === 'preview') {
      await page.getByRole('button', { name: 'Preview PDF', exact: true }).click()
    } else if (action === 'reattach') {
      page.once('dialog', dialog => dialog.accept())
      await page.getByRole('button', { name: 'Reattach Builder' }).click()
    } else {
      await page.getByRole('button', { name: /Export/ }).first().click()
      await page.getByRole('button', { name: /JSON Resume format/ }).click()
    }
    await expect(page.getByRole('heading', { name: 'Guided builder is unavailable' })).toBeVisible()
    expect(calls.writes).toBe(0)
    expect(calls.legacyWrites).toBe(0)
    expect(calls.compiles).toBe(0)
    expect(calls.exports).toBe(0)
  })
}

test('new capability plus old mutation instance fails without replaying a legacy write', async ({ page }) => {
  const calls = await setup(page)
  await page.route(CAPABILITIES, route => route.fulfill({ json: { guided_builder_version: 1 } }))
  await page.route(BUILDER, route => route.request().method() === 'PATCH'
    ? route.fulfill({ status: 404, json: { detail: 'Not Found' } })
    : route.fallback())
  await page.goto(`/workspace/builder/${ID}`)
  await page.locator('#builder-resume-title').fill('Keep this unsaved draft')
  await expect(page.getByRole('button', { name: 'Save failed · Retry' })).toBeVisible()
  await expect(page.locator('#builder-resume-title')).toHaveValue('Keep this unsaved draft')
  expect(calls.legacyWrites).toBe(0)
})
