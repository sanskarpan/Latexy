import { expect, test } from '@playwright/test'

const JOB_ID = 'review-job-1'
const OPTIMIZED = '\\documentclass{article}\n\\begin{document}\nOptimized resume\n\\end{document}'
const REVIEWED = '\\documentclass{article}\n\\begin{document}\nReviewed selection\n\\end{document}'

test('AI optimization review supports accessible per-change reject, edit, and selective apply', async ({ page }) => {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { token: 'mock-token' },
      user: { id: 'user-1', email: 'review@example.com', name: 'Review User' },
    }),
  }))
  await page.route((url) => url.pathname === '/config/feature-flags', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ trial_limits: true, upgrade_ctas: true }),
  }))
  await page.route((url) => url.pathname === '/public/trial-status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ usageCount: 0, trialLimit: 3, blocked: false }),
  }))
  await page.route((url) => url.pathname === '/ats/quick-score', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ score: 75, grade: 'C', sections_found: [], missing_sections: [] }),
  }))
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{}',
  }))
  await page.route((url) => url.pathname === '/ws/ticket', (route) => route.fulfill({
    status: 201,
    contentType: 'application/json',
    body: JSON.stringify({ ticket: 'review-ticket', expires_in: 30 }),
  }))
  await page.route((url) => url.pathname === '/jobs/submit', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, job_id: JOB_ID, message: 'Started' }),
  }))
  await page.route((url) => url.pathname === `/jobs/${JOB_ID}/state`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }),
  }))

  await page.routeWebSocket('**/ws/jobs**', (ws) => {
    ws.onMessage((raw) => {
      const message = JSON.parse(String(raw))
      if (message.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
      }
      if (message.type !== 'subscribe' || message.job_id !== JOB_ID) return
      ws.send(JSON.stringify({ type: 'subscribed', job_id: JOB_ID, replayed_count: 0 }))
      setTimeout(() => {
        const base = { job_id: JOB_ID, timestamp: Date.now() / 1000 }
        ws.send(JSON.stringify({
          type: 'event',
          event: { ...base, type: 'job.queued', event_id: '1-0', sequence: 1, job_type: 'combined', user_id: 'user-1', estimated_seconds: 1 },
        }))
        ws.send(JSON.stringify({
          type: 'event',
          event: { ...base, type: 'llm.complete', event_id: '2-0', sequence: 2, full_content: OPTIMIZED, tokens_total: 42 },
        }))
        ws.send(JSON.stringify({
          type: 'event',
          event: {
            ...base,
            type: 'job.completed',
            event_id: '3-0',
            sequence: 3,
            pdf_job_id: '',
            ats_score: 80,
            ats_details: {},
            changes_made: [{ section: 'Experience', change_type: 'modified', reason: 'Stronger result' }],
            compilation_time: 1,
            optimization_time: 1,
            tokens_used: 42,
            page_count: 1,
          },
        }))
      }, 50)
    })
  })

  const hunks = [
    {
      id: 'experience-change', kind: 'modified', original_text: 'Old result', new_text: 'New result',
      before_context: '', after_context: '', section: 'Experience', rationale: 'Stronger result',
      original_start: 10, original_end: 20,
    },
    {
      id: 'skills-change', kind: 'added', original_text: '', new_text: 'TypeScript',
      before_context: '', after_context: '', section: 'Skills', rationale: null,
      original_start: 20, original_end: 20,
    },
  ]
  await page.route((url) => url.pathname === '/optimize/segment-changes', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ hunks, summary: { total: 2, added: 1, modified: 1, removed: 0 } }),
  }))
  await page.route((url) => url.pathname === '/optimize/apply-changes', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ latex: REVIEWED }),
  }))

  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'AI Optimize' }).first().click()
  await page.getByRole('button', { name: 'Optimize for this role' }).click()
  await expect(page.getByText('AI optimization is ready. Your resume is still unchanged.')).toBeVisible({ timeout: 15_000 })

  await page.getByRole('button', { name: 'Review changes' }).click()
  let dialog = page.getByRole('dialog', { name: 'Review changes' })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()

  await page.getByRole('button', { name: 'Review changes' }).click()
  dialog = page.getByRole('dialog', { name: 'Review changes' })
  await dialog.getByRole('button', { name: 'Reject modified change in Experience' }).click()
  await dialog.getByRole('button', { name: 'Edit added change in Skills' }).click()
  await dialog.getByRole('textbox', { name: 'Edit suggested LaTeX for Skills' }).fill('TypeScript and Go')

  const applyRequest = page.waitForRequest((request) => (
    request.method() === 'POST' && new URL(request.url()).pathname === '/optimize/apply-changes'
  ))
  await dialog.getByRole('button', { name: 'Apply 1 change' }).click()
  const payload = JSON.parse((await applyRequest).postData() ?? '{}')
  expect(payload.accepted_ids).toEqual(['skills-change'])
  expect(payload.hunks.find((h: { id: string }) => h.id === 'skills-change').new_text).toBe('TypeScript and Go')

  await expect(dialog).toBeHidden()
  await expect(page.getByText('AI rewrote your resume.')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
  ).__latexyMonacoEditor?.getValue())).toBe(REVIEWED)
})
