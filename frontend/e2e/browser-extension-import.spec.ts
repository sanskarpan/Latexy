import { expect, test } from '@playwright/test'

const CAPTURE_ID = '11111111-1111-4111-8111-111111111111'
const EMPTY_BOARD = {
  applied: [], phone_screen: [], technical: [], onsite: [], offer: [], rejected: [], withdrawn: [],
}

test('imports an extension capture into the authenticated tracker review flow', async ({ page }) => {
  let submitted: Record<string, unknown> | null = null
  await page.addInitScript(({ captureId }) => {
    window.addEventListener('message', (event) => {
      const message = event.data
      if (
        event.source === window &&
        message?.source === 'latexy-web' &&
        message?.type === 'LXY_CAPTURE_REQUEST' &&
        message?.captureId === captureId
      ) {
        window.postMessage({
          source: 'latexy-extension',
          type: 'LXY_CAPTURE_RESPONSE',
          captureId,
          capture: {
            company: 'Acme Corp',
            title: 'Senior Platform Engineer',
            description: 'Own platform reliability and mentor engineers.',
            location: 'Remote — India',
            url: 'https://jobs.example/roles/123',
            source: 'json_ld',
          },
          error: null,
        }, window.location.origin)
      }
    })
  }, { captureId: CAPTURE_ID })

  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { token: 'mock-token' },
      user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
    }),
  }))
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' }))
  await page.route((url) => url.pathname === '/tracker/applications', async (route) => {
    if (route.request().method() === 'POST') {
      submitted = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'app-1', user_id: 'user-1', status: 'applied',
          company_name: submitted.company_name, role_title: submitted.role_title,
          job_description_text: submitted.job_description_text, job_url: submitted.job_url,
          notes: submitted.notes, resume_id: null, ats_score_at_submission: null,
          company_logo_url: null, applied_at: new Date().toISOString(),
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ by_status: EMPTY_BOARD }),
    })
  })
  await page.route((url) => url.pathname === '/resumes/', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ resumes: [], total: 0, page: 1, pages: 1 }),
  }))

  await page.goto(`/tracker?capture_id=${CAPTURE_ID}`, { waitUntil: 'domcontentloaded' })
  const dialog = page.getByRole('dialog', { name: 'Add Application' })
  await expect(dialog).toBeVisible({ timeout: 10_000 })
  await expect(dialog.getByText(/Imported from the browser extension/)).toBeVisible()
  await expect(dialog.getByLabel('Company *')).toHaveValue('Acme Corp')
  await expect(dialog.getByLabel('Role *')).toHaveValue('Senior Platform Engineer')
  await expect(dialog.getByLabel('Job URL')).toHaveValue('https://jobs.example/roles/123')
  await expect(dialog.getByPlaceholder('Paste the full job description...')).toHaveValue(
    'Own platform reliability and mentor engineers.',
  )
  await expect(page).toHaveURL(/\/tracker$/)

  await dialog.getByRole('button', { name: 'Add Application' }).click()
  await expect(page.getByText('Acme Corp', { exact: true }).first()).toBeVisible()
  expect(submitted).toMatchObject({
    company_name: 'Acme Corp',
    role_title: 'Senior Platform Engineer',
    job_description_text: 'Own platform reliability and mentor engineers.',
    job_url: 'https://jobs.example/roles/123',
    notes: 'Location: Remote — India',
  })
})
