import { expect, test, type Page } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route(url => url.pathname === '/config/entitlements', route => route.fulfill({
    json: { features: { b08: true, c01: true } },
  }))
  await page.route('**/resumes/builder/capabilities', route => route.fulfill({ json: { guided_builder_version: 1 } }))
})

const OWNER_A_RESUME = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const TEMPLATE_A = '11111111-1111-1111-1111-111111111111'
const TEMPLATE_B = '22222222-2222-2222-2222-222222222222'

const STRUCTURED = {
  basics: {
    name: 'Builder User', label: 'Engineer', email: 'builder@example.com', phone: '',
    location: '', website: '', linkedin: '', github: '', summary: 'Builder summary',
  },
  experience: [], education: [], projects: [], skills: [], certifications: [], awards: [],
  languages: [], interests: [],
  section_order: ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests'],
  hidden_sections: [],
}

function builderResponse({
  id,
  owner,
  status = 'active',
  templateId,
}: { id: string; owner: string; status?: 'active' | 'detached'; templateId: string }) {
  const title = owner === 'owner-a' ? 'Owner A builder' : 'Owner B builder'
  const family = owner === 'owner-a' ? 'ats' : 'executive'
  return {
    resume: {
      id,
      user_id: owner,
      title,
      latex_content: '\\documentclass{article}\\begin{document}Builder\\end{document}',
      is_template: false,
      parent_resume_id: null,
      variant_count: 0,
      selected_template_id: templateId,
      content_source: 'builder',
      builder_status: status,
      structured_content: STRUCTURED,
      structured_version: 1,
      created_at: '2026-05-29T00:00:00Z',
      updated_at: '2026-05-29T00:00:00Z',
      document_type: 'resume',
      metadata: {},
    },
    metrics: { completeness_score: 84, page_estimate: 1, warnings: [], missing_sections: [] },
    preview: { template_family: family, sections: [] },
    template_family: family,
  }
}

function templatesFor(owner: string) {
  return [
    {
      id: TEMPLATE_A,
      name: owner === 'owner-a' ? 'Owner A template' : 'Owner B template',
      description: 'Test template', category: 'ats_safe', category_label: 'ATS-Safe',
      sort_order: 0, thumbnail_url: null, pdf_url: null, template_family: 'ats',
    },
    {
      id: TEMPLATE_B,
      name: owner === 'owner-a' ? 'Owner A executive template' : 'Owner B executive template',
      description: 'Test template', category: 'executive', category_label: 'Executive',
      sort_order: 1, thumbnail_url: null, pdf_url: null, template_family: 'executive',
    },
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

test.describe('saved guided builder ownership boundaries', () => {
  test('does not apply a deferred owner-A autosave after the authenticated owner switches to B', async ({ page }) => {
    const owner = { value: 'owner-a' }
    let sessionCalls = 0
    let autosaveStarted = false
    let autosaveFinished = false
    let releaseAutosave!: () => void
    const autosaveGate = new Promise<void>(resolve => { releaseAutosave = resolve })

    await page.route('**/api/auth/get-session', route => {
      sessionCalls += 1
      const currentOwner = owner.value
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { id: `session-${currentOwner}`, userId: currentOwner, token: `token-${currentOwner}`, expiresAt: '2099-01-01T00:00:00Z' },
          user: { id: currentOwner, email: `${currentOwner}@example.com`, name: currentOwner },
        }),
      })
    })
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(templatesFor(owner.value)),
    }))
    await page.route(`**/resumes/${OWNER_A_RESUME}/builder/v1`, async route => {
      if (route.request().method() === 'GET') {
        const currentOwner = owner.value
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: currentOwner, templateId: currentOwner === 'owner-a' ? TEMPLATE_A : TEMPLATE_B })) })
      }
      if (route.request().method() === 'PATCH') {
        autosaveStarted = true
        await autosaveGate
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: 'owner-a', status: 'detached', templateId: TEMPLATE_A })),
        })
        autosaveFinished = true
        return
      }
      return route.fallback()
    })
    await page.goto(`/workspace/builder/${OWNER_A_RESUME}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Owner A builder' })).toBeVisible()
    await page.locator('#builder-resume-title').fill('Owner A changed')
    await expect.poll(() => autosaveStarted).toBe(true)

    await switchOwner(page, owner, 'owner-b')
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await expect(page.getByRole('heading', { name: 'Owner B builder' })).toBeVisible()
    await expect(page.getByRole('option', { name: 'Owner B executive template · Executive', exact: true })).toBeAttached()

    try {
      releaseAutosave()
      await expect.poll(() => autosaveFinished).toBe(true)
      await page.evaluate(() => new Promise<void>(resolve => {
        requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
      }))
      await expect(page.getByRole('heading', { name: 'Owner B builder' })).toBeVisible()
      await expect(page.getByText('Builder detached')).not.toBeVisible()
    } finally {
      releaseAutosave()
    }
  })

  test('same-owner autosave still applies its accepted terminal response', async ({ page }) => {
    let autosaves = 0
    await page.route('**/api/auth/get-session', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'session-owner-a', userId: 'owner-a', token: 'token-owner-a', expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: 'owner-a', email: 'owner-a@example.com', name: 'Owner A' },
      }),
    }))
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(templatesFor('owner-a')) }))
    await page.route(`**/resumes/${OWNER_A_RESUME}/builder/v1`, async route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: 'owner-a', templateId: TEMPLATE_A })) })
      }
      if (route.request().method() === 'PATCH') {
        autosaves += 1
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: 'owner-a', templateId: TEMPLATE_B })) })
      }
      return route.fallback()
    })

    await page.goto(`/workspace/builder/${OWNER_A_RESUME}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Owner A builder' })).toBeVisible()
    await page.locator('#builder-resume-title').fill('Owner A accepted change')
    await expect(page.getByText('All changes saved')).toBeVisible({ timeout: 10_000 })
    await expect.poll(() => autosaves).toBe(1)
    await expect(page.getByText('Builder detached')).not.toBeVisible()
  })

  test('rearms a dirty same-owner autosave after verification interrupts an in-flight save', async ({ page }) => {
    let sessionMode: 'ok' | 'error' = 'ok'
    let sessionCalls = 0
    let errorResponseFinished = false
    let recoveryResponseFinished = false
    let autosaves = 0
    let releaseFirstSave!: () => void
    let firstSaveFinished = false
    const firstSaveGate = new Promise<void>(resolve => { releaseFirstSave = resolve })

    await page.route('**/api/auth/get-session', route => {
      sessionCalls += 1
      if (sessionMode === 'error') {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary auth failure' }) }).then(() => {
          errorResponseFinished = true
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { id: 'session-owner-a', userId: 'owner-a', token: 'token-owner-a', expiresAt: '2099-01-01T00:00:00Z' },
          user: { id: 'owner-a', email: 'owner-a@example.com', name: 'Owner A' },
        }),
      }).then(() => {
        if (sessionCalls > 1) recoveryResponseFinished = true
      })
    })
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(templatesFor('owner-a')) }))
    await page.route(`**/resumes/${OWNER_A_RESUME}/builder/v1`, async route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: 'owner-a', templateId: TEMPLATE_A })) })
      }
      if (route.request().method() === 'PATCH') {
        autosaves += 1
        if (autosaves === 1) {
          await firstSaveGate
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: 'owner-a', templateId: TEMPLATE_A })) })
          firstSaveFinished = true
          return
        }
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: 'owner-a', templateId: TEMPLATE_B })) })
      }
      return route.fallback()
    })

    await page.goto(`/workspace/builder/${OWNER_A_RESUME}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Owner A builder' })).toBeVisible()
    await page.locator('#builder-resume-title').fill('Owner A interrupted save')
    await expect.poll(() => autosaves).toBe(1)

    sessionMode = 'error'
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-transient-save-error' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await expect.poll(() => errorResponseFinished).toBe(true)

    try {
      releaseFirstSave()
      await expect.poll(() => firstSaveFinished).toBe(true)
      await expect(page.getByText('Saving…')).not.toBeVisible()
      const dirtyStatus = page.getByText('Unsaved changes', { exact: true })
      await expect(dirtyStatus).toBeAttached()
      await expect(dirtyStatus).toBeHidden()
      const retainedBuilder = page.locator('main > div[hidden][inert]').filter({ has: dirtyStatus })
      await expect(retainedBuilder).toBeAttached()
      await expect(retainedBuilder.locator('h1')).toHaveText('Owner A interrupted save')
      await expect(page.getByRole('heading', { name: 'Feature unavailable', exact: true })).toBeVisible()
      await expect(page.getByText('Feature availability could not be verified.', { exact: true })).toBeVisible()
      expect(autosaves).toBe(1)

      sessionMode = 'ok'
      await page.evaluate(() => {
        const message = JSON.stringify({ event: 'session', data: { trigger: 'test-save-recovery' } })
        localStorage.setItem('better-auth.message', message)
        window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
      })
      await expect.poll(() => sessionCalls).toBeGreaterThan(2)
      await expect.poll(() => recoveryResponseFinished).toBe(true)
      await expect.poll(() => autosaves).toBe(2)
      await expect(page.getByText('All changes saved')).toBeVisible()
    } finally {
      releaseFirstSave()
    }
  })

  test('does not apply a deferred owner-A force-reattach after the authenticated owner switches to B', async ({ page }) => {
    await page.route(url => url.pathname === '/config/entitlements', route => route.fulfill({
      json: { features: { b08: true, b09: true, c01: true } },
    }))
    const owner = { value: 'owner-a' }
    let reattachStarted = false
    let reattachFinished = false
    let releaseReattach!: () => void
    const reattachGate = new Promise<void>(resolve => { releaseReattach = resolve })

    // Keep the session response dynamic so Better Auth's refresh observes B.
    await page.route('**/api/auth/get-session', route => {
      const currentOwner = owner.value
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { id: `session-${currentOwner}`, userId: currentOwner, token: `token-${currentOwner}`, expiresAt: '2099-01-01T00:00:00Z' },
          user: { id: currentOwner, email: `${currentOwner}@example.com`, name: currentOwner },
        }),
      })
    })
    await page.route('**/ws/**', route => route.abort())
    await page.route('**/resumes/builder/templates', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(templatesFor(owner.value)) }))
    await page.route(`**/resumes/${OWNER_A_RESUME}/builder/v1`, async route => {
      if (route.request().method() === 'GET') {
        const currentOwner = owner.value
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: currentOwner, status: 'detached', templateId: currentOwner === 'owner-a' ? TEMPLATE_A : TEMPLATE_B })) })
      }
      if (route.request().method() === 'PATCH') {
        reattachStarted = true
        await reattachGate
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse({ id: OWNER_A_RESUME, owner: 'owner-a', status: 'active', templateId: TEMPLATE_A })) })
        reattachFinished = true
        return
      }
      return route.fallback()
    })
    await page.goto(`/workspace/builder/${OWNER_A_RESUME}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Builder detached')).toBeVisible()
    page.once('dialog', dialog => dialog.accept())
    await page.getByRole('button', { name: /Reattach Builder/ }).click()
    await expect.poll(() => reattachStarted).toBe(true)

    await switchOwner(page, owner, 'owner-b')
    await expect(page.getByRole('heading', { name: 'Owner B builder' })).toBeVisible()
    await expect(page.getByText('Builder detached')).toBeVisible()

    try {
      releaseReattach()
      await expect.poll(() => reattachFinished).toBe(true)
      await page.evaluate(() => new Promise<void>(resolve => {
        requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
      }))
      await expect(page.getByText('Builder detached')).toBeVisible()
    } finally {
      releaseReattach()
    }
  })
})

test('C25 saved owner recovers current local JSON across capability denial without new effects or cross-scope drafts', async ({ page }) => {
  const secondResume = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
  const owner = { value: 'owner-a' }
  const features = { b08: true, c01: true }
  let saveAttempts = 0
  let compileAttempts = 0
  await page.route(url => url.pathname === '/config/entitlements', route => route.fulfill({
    json: { features: { ...features, c05: true } },
  }))
  await page.route('**/api/auth/get-session', route => route.fulfill({
    json: {
      session: { id: `session-${owner.value}`, userId: owner.value, token: `token-${owner.value}`, expiresAt: '2099-01-01T00:00:00Z' },
      user: { id: owner.value, email: `${owner.value}@example.com`, name: owner.value },
    },
  }))
  await page.route('**/ws/**', route => route.abort())
  await page.route('**/resumes/builder/templates', route => route.fulfill({ json: templatesFor(owner.value) }))
  await page.route(url => /\/resumes\/[^/]+\/builder\/v1$/.test(url.pathname), route => {
    if (route.request().method() === 'PATCH') {
      saveAttempts += 1
      // A real rejected save leaves unsaved work in place and stops autosave.
      // This scenario measures recovery reads, not B08 write admission.
      return route.fulfill({ status: 409, json: { detail: 'A newer structured version exists' } })
    }
    const parts = new URL(route.request().url()).pathname.split('/')
    const id = parts[parts.length - 3]
    const response = builderResponse({ id, owner: owner.value, templateId: owner.value === 'owner-a' ? TEMPLATE_A : TEMPLATE_B })
    if (id === secondResume) response.resume.title = 'Owner B second builder'
    return route.fulfill({ json: response })
  })
  await page.route(url => /\/(?:jobs|compile)(?:\/|$)/.test(url.pathname), route => {
    if (route.request().method() === 'POST') compileAttempts += 1
    return route.abort()
  })
  const refreshFeatures = async () => {
    await page.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
  }
  const downloadDraft = async (id: string) => {
    const before = { saveAttempts, compileAttempts }
    const pending = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Download current builder draft (.json)', exact: true }).click()
    const download = await pending
    expect(download.suggestedFilename()).toBe(`latexy-builder-${id}-draft.json`)
    expect(await download.failure()).toBeNull()
    const stream = await download.createReadStream()
    expect(stream).not.toBeNull()
    const chunks: Buffer[] = []
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
    const bytes = Buffer.concat(chunks)
    expect({ saveAttempts, compileAttempts }).toEqual(before)
    const draft = JSON.parse(bytes.toString('utf8'))
    expect(Object.keys(draft).sort()).toEqual(['format', 'resume_id', 'structured_content', 'template_id', 'title', 'version'])
    expect(bytes.equals(Buffer.from(JSON.stringify(draft, null, 2)))).toBe(true)
    expect(draft).toMatchObject({ format: 'latexy-builder-draft', version: 1, resume_id: id })
    return { bytes, draft }
  }

  await page.goto(`/workspace/builder/${OWNER_A_RESUME}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Owner A builder', exact: true })).toBeVisible()
  await page.locator('#builder-resume-title').fill('Owner A unsaved recovery title')
  await page.locator('#builder-template-select').selectOption(TEMPLATE_B)
  await page.locator('#builder-basics-summary').fill('Owner A unsaved recovery summary')
  await expect(page.getByText('A newer saved version exists. Your edits are preserved here.', { exact: true })).toBeVisible()
  expect(saveAttempts).toBe(1)

  features.b08 = false
  await refreshFeatures()
  await expect(page.getByRole('heading', { name: 'Feature unavailable', exact: true })).toBeVisible()
  const retained = page.locator('main > div[hidden][inert]').filter({ has: page.getByRole('heading', { name: 'Owner A unsaved recovery title', includeHidden: true }) })
  await expect(retained).toBeAttached()
  await expect(retained).toBeHidden()
  const hiddenRecovery = await downloadDraft(OWNER_A_RESUME)
  expect(hiddenRecovery.draft).toEqual({
    format: 'latexy-builder-draft', version: 1, resume_id: OWNER_A_RESUME,
    title: 'Owner A unsaved recovery title', template_id: TEMPLATE_B,
    structured_content: { ...STRUCTURED, basics: { ...STRUCTURED.basics, summary: 'Owner A unsaved recovery summary' } },
  })

  features.b08 = true
  features.c01 = false
  await refreshFeatures()
  await expect(page.getByText('Editing guided résumé fields is unavailable.', { exact: false })).toBeVisible()
  await expect(page.locator('#builder-resume-title')).toHaveCount(0)
  const readOnlyRecovery = await downloadDraft(OWNER_A_RESUME)
  expect(readOnlyRecovery.bytes.equals(hiddenRecovery.bytes)).toBe(true)

  features.c01 = true
  await refreshFeatures()
  await expect(page.locator('#builder-resume-title')).toHaveValue('Owner A unsaved recovery title')
  await expect(page.locator('#builder-template-select')).toHaveValue(TEMPLATE_B)
  await expect(page.locator('#builder-basics-summary')).toHaveValue('Owner A unsaved recovery summary')
  expect(saveAttempts).toBe(1)
  expect(compileAttempts).toBe(0)

  features.b08 = false
  await refreshFeatures()
  await expect(page.getByRole('button', { name: 'Download current builder draft (.json)' })).toBeVisible()
  await switchOwner(page, owner, 'owner-b')
  await expect(page.getByRole('button', { name: 'Download current builder draft (.json)' })).toHaveCount(0)
  features.b08 = true
  await refreshFeatures()
  await expect(page.getByRole('heading', { name: 'Owner B builder', exact: true })).toBeVisible()
  features.c01 = false
  await refreshFeatures()
  const ownerB = await downloadDraft(OWNER_A_RESUME)
  expect(ownerB.draft.title).toBe('Owner B builder')
  expect(ownerB.bytes.toString('utf8')).not.toContain('Owner A unsaved')

  // A fresh document must offer only its own loaded state, never the old draft.
  await page.goto(`/workspace/builder/${secondResume}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Owner B second builder', exact: true })).toBeVisible()
  const nextDocument = await downloadDraft(secondResume)
  expect(nextDocument.draft.title).toBe('Owner B second builder')
  expect(nextDocument.bytes.toString('utf8')).not.toContain('Owner A unsaved')
  expect(saveAttempts).toBe(1)
  expect(compileAttempts).toBe(0)
})
