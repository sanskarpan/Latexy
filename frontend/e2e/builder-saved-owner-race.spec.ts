import { expect, test, type Page } from '@playwright/test'

test.beforeEach(async ({ page }) => {
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
      await expect(page.getByText('Unsaved changes')).toBeVisible()

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
