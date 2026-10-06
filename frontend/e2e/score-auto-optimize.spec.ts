import { expect, test } from '@playwright/test'

const RESUME_ID = 'aaaaaaaa-1111-4111-8111-111111111111'
const ORIGINAL = String.raw`\documentclass{article}
\begin{document}
\section*{Experience}
Built backend services for a growing payments platform and collaborated with product teams on delivery.
\section*{Education}
BSc Computer Science
\end{document}`
const OPTIMIZED = ORIGINAL.replace('Built backend services', 'Engineered resilient backend services')
const REVIEWED = OPTIMIZED.replace('growing', 'high-growth')

test('score report creates a findings-guided draft and automatically opens per-change review', async ({ page }) => {
  let submission = 0
  let scoreRequest: Record<string, unknown> | null = null
  let localeRequest: Record<string, unknown> | null = null
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token')
    localStorage.setItem('latexy_onboarding_completed', 'true')
  })
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ session: { token: 'test-token' }, user: { id: 'user-1', email: 'test@example.com', name: 'Taylor' } }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ id: RESUME_ID, user_id: 'user-1', title: 'Platform Resume', latex_content: ORIGINAL, created_at: '2026-09-14T00:00:00Z', updated_at: '2026-09-14T00:00:00Z', metadata: {} }),
  }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }),
  }))
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/ats/industry-profiles', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"profiles":[]}' }))
  await page.route((url) => url.pathname === '/ats/locale-profiles', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, threshold: 80, profiles: [
      { key: 'global', label: 'Global / role-only', calibration: 'Global checks' },
      { key: 'india', label: 'India', calibration: 'Indian conventions' },
      { key: 'united_states', label: 'United States', calibration: 'US hiring conventions' },
      { key: 'united_kingdom', label: 'United Kingdom', calibration: 'UK hiring conventions' },
    ] }),
  }))
  await page.route((url) => url.pathname === '/ats/score', async (route) => {
    localeRequest = route.request().postDataJSON()
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        success: true, ats_score: 52, category_scores: { content: 45 },
        recommendations: ['Add measurable outcomes where evidence exists'], warnings: ['Skills section is missing'], strengths: [],
        industry_key: 'generic', locale_key: 'united_states', locale_label: 'United States', score_threshold: 80,
        calibration_statement: 'Latexy document-quality checks with US hiring conventions; sensitive personal details are discouraged.',
        message: 'Complete',
      }),
    })
  })
  await page.route((url) => url.pathname.includes('/benchmark'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"sufficient_data":false,"percentile":null,"sample_size":0}' }))
  await page.route((url) => url.pathname === '/ws/ticket', (route) => route.fulfill({ status: 201, contentType: 'application/json', body: '{"ticket":"score-ticket","expires_in":30}' }))
  await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
    submission += 1
    const body = route.request().postDataJSON()
    const jobId = submission === 1 ? 'initial-score-job' : submission === 2 ? 'report-optimize-job' : 'review-compile-job'
    if (submission === 2) scoreRequest = body
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: jobId, message: 'Started' }) })
  })
  await page.route((url) => /\/jobs\/[^/]+\/state$/.test(url.pathname), (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }),
  }))
  await page.route((url) => url.pathname.startsWith('/download/'), (route) => route.fulfill({ status: 404, body: 'not needed' }))

  await page.routeWebSocket('**/ws/jobs**', (socket) => {
    const sent = new Set<string>()
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw))
      if (message.type === 'ping') socket.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
      const jobId = message.job_id as string
      if (message.type !== 'subscribe' || sent.has(jobId)) return
      sent.add(jobId)
      socket.send(JSON.stringify({ type: 'subscribed', job_id: jobId, replayed_count: 0 }))
      setTimeout(() => {
        const base = { job_id: jobId, timestamp: Date.now() / 1000 }
        if (jobId === 'report-optimize-job') {
          socket.send(JSON.stringify({ type: 'event', event: { ...base, type: 'llm.complete', event_id: `${jobId}-1`, sequence: 1, full_content: OPTIMIZED, tokens_total: 30 } }))
        }
        socket.send(JSON.stringify({
          type: 'event',
          event: {
            ...base, type: 'job.completed', event_id: `${jobId}-2`, sequence: 2, pdf_job_id: '',
            ats_score: jobId === 'initial-score-job' ? 58 : 76,
            ats_details: {
              category_scores: { content: 55 },
              recommendations: ['Add measurable outcomes where evidence exists'],
              warnings: ['Skills section is missing'], strengths: [],
            },
            changes_made: [], compilation_time: 1, optimization_time: 1, tokens_used: 30, page_count: 1,
          },
        }))
      }, 50)
    })
  })

  await page.route((url) => url.pathname === '/optimize/segment-changes', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ hunks: [{ id: 'h1', kind: 'modified', original_text: 'Built backend services', new_text: 'Engineered resilient backend services', before_context: '', after_context: '', section: 'Experience', rationale: 'ATS recommendation', original_start: 0, original_end: 22 }], summary: { total: 1, added: 0, modified: 1, removed: 0 } }),
  }))
  await page.route((url) => url.pathname === '/optimize/apply-changes', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ latex: REVIEWED }) }))

  await page.goto(`/workspace/${RESUME_ID}/optimize`)
  const action = page.getByRole('button', { name: 'Apply recommended changes' })
  await expect(action).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/80 or higher.*good-score threshold/)).toBeVisible()
  await page.getByLabel('ATS locale').selectOption('united_states')
  await expect.poll(() => localeRequest).not.toBeNull()
  expect(localeRequest).toMatchObject({ locale: 'united_states' })
  await expect(page.getByText(/Calibrated against:.*US hiring conventions/)).toBeVisible()
  await action.click()
  await expect.poll(() => scoreRequest).not.toBeNull()
  const captured = scoreRequest as Record<string, unknown> | null
  expect(captured).toMatchObject({ job_type: 'combined', latex_content: ORIGINAL })
  expect(String(captured?.custom_instructions)).toContain('Add measurable outcomes where evidence exists')
  expect(String(captured?.custom_instructions)).toContain('Skills section is missing')

  const dialog = page.getByRole('dialog', { name: 'Review changes' })
  await expect(dialog).toBeVisible({ timeout: 15_000 })
  await dialog.getByRole('button', { name: 'Apply 1 change' }).click()
  await expect(dialog).toBeHidden()
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
  ).__latexyMonacoEditor?.getValue())).toBe(REVIEWED)
})
