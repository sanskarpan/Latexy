import { test, expect, type Page } from '@playwright/test'

const SESSION = { session: { token: 'tracker-e2e-token' }, user: { id: 'tracker-user', email: 'tracker@example.com', name: 'Tracker User' } }
const APP = { id: '11111111-1111-1111-1111-111111111111', user_id: 'tracker-user', company_name: 'Acme', role_title: 'Engineer', status: 'applied', resume_id: null, ats_score_at_submission: 82, job_description_text: null, job_url: 'https://example.com/jobs/1', company_logo_url: null, notes: null, applied_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z', created_at: '2025-01-01T00:00:00Z' }
const SAVED = { id: '22222222-2222-2222-2222-222222222222', company_name: 'Globex', role_title: 'Designer', job_url: 'https://example.com/jobs/2', job_description_text: 'Design systems', notes: 'Follow up', created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }

async function mockTracker(page: Page) {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }))
  await page.route((url) => url.pathname === '/tracker/applications', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: { applied: [APP], phone_screen: [], technical: [], onsite: [], offer: [], rejected: [], withdrawn: [] } }) }))
  await page.route((url) => url.pathname === '/tracker/stats', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total_applications: 1, by_status: { applied: 1 }, avg_ats_score: 82, applications_this_week: 0, applications_this_month: 0, response_rate: 0, offer_rate: 0 }) }))
  await page.route((url) => url.pathname === '/tracker/stale-applications', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ ...APP, days_since_update: 20 }]) }))
  let savedJobs = [SAVED]
  await page.route((url) => url.pathname === '/tracker/saved-jobs' || !!url.pathname.match(/\/tracker\/saved-jobs\/[^/]+$/), async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (request.method() === 'POST') { const body = request.postDataJSON(); const created = { ...SAVED, id: 'saved-1', ...body }; savedJobs = [created, ...savedJobs]; return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(created) }) }
    if (request.method() === 'PUT') { const id = pathname.split('/').pop() as string; const updated = { ...savedJobs.find((job) => job.id === id), ...request.postDataJSON() }; savedJobs = savedJobs.map((job) => job.id === id ? updated : job); return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(updated) }) }
    if (request.method() === 'DELETE') { savedJobs = savedJobs.filter((job) => job.id !== pathname.split('/').pop()); return route.fulfill({ status: 204, body: '' }) }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(savedJobs) })
  })
  await page.route((url) => url.pathname === '/tracker/alerts', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname === '/tracker/contacts', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname === '/tracker/companies', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
}

test.describe('tracker workflows', () => {
  test('switches between Board, Saved jobs, Alerts, and Contacts', async ({ page }) => {
    await mockTracker(page)
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Job Applications' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Needs a follow-up' })).toBeVisible()
    await expect(page.getByText(/not an employer-response signal/)).toBeVisible()
    await expect(page.getByText('20d since your last update · Add reminder')).toBeVisible()
    await expect(page.getByText(/ghosted/i)).toHaveCount(0)
    await expect(page.getByText('20d stale · Add reminder')).toHaveCount(0)
    await page.getByRole('button', { name: 'Saved jobs' }).click()
    await expect(page.getByRole('heading', { name: 'Saved jobs' })).toBeVisible()
    await page.getByRole('button', { name: 'Alerts' }).click()
    await expect(page.getByRole('heading', { name: 'Alerts' })).toBeVisible()
    await page.getByRole('button', { name: 'Contacts' }).click()
    await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible()
  })

  test('creates a saved job and opens application follow-ups', async ({ page }) => {
    await mockTracker(page)
    const reminder = { id: 'reminder-1', application_id: APP.id, remind_at: '2099-01-01T10:00:00Z', note: 'Follow up', sent_at: null, created_at: '2025-01-01T00:00:00Z' }
    const interview = { id: 'interview-1', application_id: APP.id, round_name: 'Screen', interview_format: 'video', starts_at: '2099-01-02T10:00:00Z', duration_minutes: 60, timezone: 'UTC', location: 'Meet', interviewers: ['Jane'], notes: null, created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }
    await page.route((url) => url.pathname.includes('/reminders') || url.pathname.includes('/interviews'), async (route) => {
      const method = route.request().method()
      const pathname = new URL(route.request().url()).pathname
      if (method === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      if (pathname.endsWith('/reminders')) return route.fulfill({ status: method === 'POST' ? 201 : 200, contentType: 'application/json', body: JSON.stringify({ ...reminder, ...(route.request().postDataJSON() || {}) }) })
      return route.fulfill({ status: method === 'POST' ? 201 : 200, contentType: 'application/json', body: JSON.stringify({ ...interview, ...(route.request().postDataJSON() || {}) }) })
    })
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Saved jobs' }).click()
    await page.getByLabel('Company').fill('Globex')
    await page.getByLabel('Role title').fill('Designer')
    await page.getByRole('button', { name: 'Save job' }).click()
    await expect(page.getByRole('heading', { name: 'Designer' }).first()).toBeVisible()
    await page.getByRole('button', { name: 'Board' }).click()
    await page.getByRole('button', { name: /Actions for Acme/ }).click()
    await page.getByRole('menuitem', { name: 'Follow-ups' }).click()
    await expect(page.getByRole('heading', { name: /Follow-ups/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Reminders' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Interviews' })).toBeVisible()
    await page.getByLabel('Remind me').fill('2099-01-01T10:00')
    await page.getByLabel('Reminder note').fill('Follow up')
    await page.getByRole('button', { name: 'Add reminder', exact: true }).click()
    await expect(page.getByText(/Follow up/)).toBeVisible()
    await page.getByRole('button', { name: 'Edit', exact: true }).first().click()
    await page.getByRole('dialog').locator('input[type="datetime-local"]').first().fill('2099-01-03T10:00')
    await page.getByRole('button', { name: 'Reschedule reminder' }).click()
    await expect(page.getByText(/Follow up/)).toBeVisible()
    await page.getByLabel('Interview round').fill('Screen')
    await page.getByLabel('Interview start time').fill('2099-01-02T10:00')
    await page.getByRole('button', { name: 'Schedule interview' }).click()
    await expect(page.getByText('Screen', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Add to calendar' })).toBeVisible()
    await page.getByRole('button', { name: 'Edit', exact: true }).last().click()
    await page.getByLabel('Interview round').fill('Final')
    await page.getByRole('button', { name: 'Update interview' }).click()
    await expect(page.getByText('Final', { exact: true })).toBeVisible()
  })

  test('edits and bulk removes saved jobs', async ({ page }) => {
    await mockTracker(page)
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Saved jobs' }).click()
    await expect(page.getByText('Designer')).toBeVisible()
    await page.getByRole('button', { name: 'Edit' }).click()
    await page.getByLabel('Role title').fill('Senior Designer')
    await page.getByRole('button', { name: 'Update job' }).click()
    await expect(page.getByText('Senior Designer')).toBeVisible()
    await page.getByLabel('Select Senior Designer').check()
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: /Remove selected/ }).click()
    await expect(page.getByText('No saved jobs yet.')).toBeVisible()
  })

  test('keeps a retryable error when a resource list fails', async ({ page }) => {
    await mockTracker(page)
    let failed = true
    await page.route((url) => url.pathname === '/tracker/alerts', (route) => {
      if (failed) { failed = false; return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'temporarily unavailable' }) }) }
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Alerts' }).click()
    const resourceError = page.getByRole('alert').filter({ hasText: 'temporarily unavailable' })
    await expect(resourceError).toBeVisible()
    await resourceError.getByRole('button', { name: 'Retry' }).click()
    await expect(page.getByText('No alerts yet.')).toBeVisible()
  })

  test('edits and pauses an alert with explicit source guidance', async ({ page }) => {
    await mockTracker(page)
    const alert = { id: 'alert-1', query: 'React', company_name: 'Acme', location: 'Remote', source_url: 'https://example.com/search', frequency: 'daily', active: true, last_notified_at: null, created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }
    const alertPayloads: Array<Record<string, unknown>> = []
    await page.route((url) => url.pathname.startsWith('/tracker/alerts'), async (route) => {
      if (route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([alert]) })
      if (route.request().method() === 'PUT') { const body = route.request().postDataJSON() || {}; alertPayloads.push(body); return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...alert, ...body }) }) }
      return route.fulfill({ status: 204, body: '' })
    })
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Alerts' }).click()
    await expect(page.getByText(/does not scrape or discover jobs/)).toBeVisible()
    await page.getByRole('button', { name: 'Edit' }).click()
    await page.getByLabel('Search query').fill('TypeScript')
    await page.getByRole('button', { name: 'Update alert' }).click()
    await expect(page.getByText('TypeScript')).toBeVisible()
    await expect.poll(() => alertPayloads[0]?.query).toBe('TypeScript')
    await page.getByRole('switch', { name: /Alert TypeScript/ }).click()
    await expect.poll(() => alertPayloads[alertPayloads.length - 1]?.active).toBe(false)
  })

  test('creates and edits a contact with a company assignment', async ({ page }) => {
    await mockTracker(page)
    const company = { id: 'company-1', name: 'Acme', website: 'https://acme.example', notes: null, created_at: '2025-01-01T00:00:00Z' }
    const contact = { id: 'contact-1', company_id: company.id, name: 'Jane Recruiter', role_title: 'Recruiter', email: 'jane@acme.example', phone: null, linkedin_url: 'https://linkedin.com/in/jane', notes: 'Warm intro', created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }
    const contactPayloads: Array<Record<string, unknown>> = []
    await page.route((url) => url.pathname.startsWith('/tracker/companies'), async (route) => route.fulfill({ status: route.request().method() === 'POST' ? 201 : 200, contentType: 'application/json', body: JSON.stringify(route.request().method() === 'GET' ? [] : company) }))
    await page.route((url) => url.pathname.startsWith('/tracker/contacts'), async (route) => { const body = route.request().postDataJSON() || {}; if (route.request().method() === 'POST' || route.request().method() === 'PUT') contactPayloads.push(body); return route.fulfill({ status: route.request().method() === 'POST' ? 201 : 200, contentType: 'application/json', body: JSON.stringify(route.request().method() === 'GET' ? [] : { ...contact, ...body }) }) })
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Contacts' }).click()
    await page.getByLabel('Company name').fill('Acme')
    await page.getByRole('button', { name: 'Add company' }).click()
    await page.getByLabel('Contact name').fill('Jane Recruiter')
    await page.getByLabel('Contact role').fill('Recruiter')
    await page.getByLabel('Contact email').fill('jane@acme.example')
    await page.getByLabel('LinkedIn URL').fill('https://linkedin.com/in/jane')
    await page.getByLabel('Contact company').selectOption(company.id)
    await page.getByRole('button', { name: 'Add contact' }).click()
    await expect(page.getByText('Jane Recruiter')).toBeVisible()
    await expect.poll(() => contactPayloads[0]?.company_id).toBe(company.id)
    await page.getByRole('button', { name: 'Edit', exact: true }).last().click()
    await page.getByLabel('Contact role').fill('Senior Recruiter')
    await page.getByLabel('Contact company').selectOption('')
    await page.getByRole('button', { name: 'Update contact' }).click()
    await expect(page.getByText(/Senior Recruiter/)).toBeVisible()
    await expect.poll(() => contactPayloads[contactPayloads.length - 1]?.company_id).toBe(null)
  })

  test('generates an editable unsent outreach draft and retries failures', async ({ page }) => {
    await mockTracker(page)
    const contact = { id: 'contact-1', company_id: null, name: 'Jane Recruiter', role_title: 'Recruiter', email: null, phone: null, linkedin_url: null, notes: null, created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }
    await page.route((url) => url.pathname === '/tracker/contacts', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([contact]) }))
    let attempts = 0
    const requests: Array<Record<string, unknown>> = []
    await page.route((url) => url.pathname === '/outreach/drafts', async (route) => { attempts += 1; const body = route.request().postDataJSON(); requests.push(body); if (attempts === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'draft provider unavailable' }) }); return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ application_id: APP.id, contact_id: contact.id, recipient_name: contact.name, recipient_role: contact.role_title, company_name: 'Acme', role_title: 'Engineer', stage: 'Applied', channel: 'linkedin', purpose: 'networking', subject: 'Connect about Engineer', body: 'Hello Jane, I would love to connect.', placeholders: ['shared connection'], editable: true, sent: false }) }) })
    await page.addInitScript(() => { let copied = ''; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (value: string) => { copied = value }, readText: async () => copied } }) })
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /Actions for Acme/ }).click()
    await page.getByRole('menuitem', { name: 'Draft outreach' }).click()
    await page.getByLabel('Contact (optional)').selectOption(contact.id)
    await page.getByLabel('Channel').selectOption('linkedin')
    await page.getByLabel('Purpose').selectOption('networking')
    await page.getByLabel('Additional context').fill('Met at the conference')
    await page.getByRole('button', { name: 'Generate draft' }).click()
    const outreachError = page.getByRole('alert').filter({ hasText: 'draft provider unavailable' })
    await expect(outreachError).toBeVisible()
    await outreachError.getByRole('button', { name: 'Retry' }).click()
    await expect(page.getByRole('textbox', { name: 'Subject' })).toHaveValue('Connect about Engineer')
    await expect(page.getByText(/Editable draft — not sent/)).toBeVisible()
    await expect(page.getByRole('textbox', { name: 'Body' })).toHaveValue('Hello Jane, I would love to connect.')
    await expect(page.getByText('Review checklist', { exact: true })).toBeVisible()
    await expect(page.getByRole('listitem').filter({ hasText: 'shared connection' })).toBeVisible()
    await expect.poll(() => attempts).toBe(2)
    await expect.poll(() => requests.some((request) => request.channel === 'linkedin')).toBe(true)
    await expect.poll(() => requests.some((request) => request.purpose === 'networking')).toBe(true)
    await expect.poll(() => requests.some((request) => request.contact_id === contact.id)).toBe(true)
    await page.getByRole('textbox', { name: 'Subject' }).fill('Edited subject')
    await page.getByRole('button', { name: 'Copy subject' }).click()
    await expect(page.getByText('Subject copied')).toBeVisible()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('Edited subject')
  })

  test('reviews one forwarded email with retry and never mutates application status', async ({ page }) => {
    await mockTracker(page)
    let attempts = 0
    const parseRequests: Array<Record<string, unknown>> = []
    const trackerMutations: string[] = []
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.pathname.startsWith('/tracker/applications/') && request.method() !== 'GET') trackerMutations.push(request.method())
    })
    await page.route((url) => url.pathname === '/tracker/email-status/parse', async (route) => {
      attempts += 1
      parseRequests.push(route.request().postDataJSON())
      if (attempts === 1) return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Invalid forwarded email' }) })
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'phone_screen', company: 'Acme', role: 'Engineer', confidence: 0.91, company_confidence: 0.95, role_confidence: 0.88, evidence: [{ signal: 'interview invitation', source: 'X-Thread-Topic header' }, { signal: 'company name', source: 'From header' }], requires_review: true }) })
    })
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Review forwarded email' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    const rawEmail = 'From: recruiting@acme.example\r\nSubject: Interview update\r\n\r\nPlease choose a time.'
    await page.getByLabel('Raw forwarded email').fill(rawEmail)
    await page.getByRole('button', { name: 'Review email' }).click()
    const parseError = page.getByRole('alert').filter({ hasText: 'Invalid forwarded email' })
    await expect(parseError).toBeVisible()
    await parseError.getByRole('button', { name: 'Retry' }).click()
    await expect(page.getByRole('heading', { name: 'Suggested details' })).toBeVisible()
    await expect(page.getByText('phone_screen')).toBeVisible()
    await expect(page.getByText('91%')).toBeVisible()
    await expect(page.getByText('interview invitation')).toBeVisible()
    await expect(page.getByText('X-Thread-Topic header')).toBeVisible()
    await expect(page.getByText(/Review required — no automatic updates/)).toBeVisible()
    await expect(page.getByText(/does not access your mailbox/)).toBeVisible()
    await expect(page.getByText(/does not .* retain the pasted message/)).toBeVisible()
    await expect.poll(() => attempts).toBe(2)
    await expect.poll(() => String(parseRequests[1]?.raw_email ?? '')).toContain('Subject: Interview update')
    await expect.poll(() => trackerMutations.length).toBe(0)
  })
})
