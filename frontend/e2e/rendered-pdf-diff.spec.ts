import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const ORIGINAL = '\\documentclass{article}\n\\begin{document}\nOriginal resume\n\\end{document}'
const OPTIMIZED = '\\documentclass{article}\n\\begin{document}\nOptimized resume with impact\n\\end{document}'

function makePdf(text: string): Buffer {
  const escaped = text.replace(/([\\()])/g, '\\$1')
  const stream = `BT /F1 24 Tf 72 700 Td (${escaped}) Tj ET`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let pdf = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf))
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
  })
  const xrefOffset = Buffer.byteLength(pdf)
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  return Buffer.from(pdf)
}

async function mockPage(page: Page) {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { token: 'mock-token' },
      user: { id: 'user-1', email: 'diff@example.com', name: 'Diff User' },
    }),
  }))
  await page.route((url) => url.pathname === '/config/feature-flags', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ trial_limits: true, deep_analysis_trial: true, compile_timeouts: true, task_priority: true, billing: true, upgrade_ctas: true }),
  }))
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) => route.fulfill({ status: 200, body: '{}' }))
  await page.route((url) => url.pathname === '/ats/quick-score', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ score: 75, grade: 'C', sections_found: [], missing_sections: [], keyword_match_percent: null }),
  }))
  await page.route((url) => url.pathname.startsWith('/format'), (route) => route.fulfill({ status: 200, body: '{"supported":true}' }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: 'user-1',
      title: 'Rendered Diff Resume',
      latex_content: ORIGINAL,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/checkpoints`, (route) => route.fulfill({ status: 200, body: '[]' }))
  await page.route((url) => url.pathname === '/ws/ticket', (route) => route.fulfill({
    status: 201,
    contentType: 'application/json',
    body: JSON.stringify({ ticket: 'diff-ticket', expires_in: 30 }),
  }))

  let submission = 0
  await page.route((url) => url.pathname === '/jobs/submit', (route) => {
    submission += 1
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: submission === 1 ? 'optimize-job' : 'original-job', message: 'Started' }),
    })
  })
  await page.route((url) => /\/jobs\/(optimize|original)-job\/state/.test(url.pathname), (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }),
  }))
  await page.route((url) => url.pathname === '/download/optimized-pdf', (route) => route.fulfill({
    status: 200,
    contentType: 'application/pdf',
    body: makePdf('Optimized resume with impact'),
  }))
  await page.route((url) => url.pathname === '/download/original-pdf', (route) => route.fulfill({
    status: 200,
    contentType: 'application/pdf',
    body: makePdf('Original resume'),
  }))

  await page.routeWebSocket('**/ws/jobs**', (ws) => {
    ws.onMessage((raw) => {
      const message = JSON.parse(String(raw))
      if (message.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
        return
      }
      if (message.type !== 'subscribe') return
      const jobId = message.job_id as string
      ws.send(JSON.stringify({ type: 'subscribed', job_id: jobId, replayed_count: 0 }))
      setTimeout(() => {
        const base = { job_id: jobId, timestamp: Date.now() / 1000 }
        if (jobId === 'optimize-job') {
          ws.send(JSON.stringify({
            type: 'event',
            event: { ...base, type: 'llm.complete', event_id: '1-0', sequence: 1, full_content: OPTIMIZED, tokens_total: 25 },
          }))
        }
        ws.send(JSON.stringify({
          type: 'event',
          event: {
            ...base,
            type: 'job.completed',
            event_id: jobId === 'optimize-job' ? '2-0' : '3-0',
            sequence: 2,
            pdf_job_id: jobId === 'optimize-job' ? 'optimized-pdf' : 'original-pdf',
            ats_score: 80,
            ats_details: {},
            changes_made: [],
            compilation_time: 1,
            optimization_time: jobId === 'optimize-job' ? 1 : 0,
            tokens_used: jobId === 'optimize-job' ? 25 : 0,
            page_count: 1,
          },
        }))
      }, 50)
    })
  })
}

test('before/after comparison renders a highlighted visual PDF diff', async ({ page }) => {
  test.setTimeout(180_000)
  await mockPage(page)
  await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: 'Optimize Resume' })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Optimize Resume' }).click()
  await expect(page.getByRole('button', { name: 'Compare with Original' })).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Compare with Original' }).click()

  const dialog = page.getByRole('dialog', { name: 'Before / After Optimization' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('tab', { name: 'PDF Preview' }).click()
  await dialog.getByRole('button', { name: 'Compile Original' }).click()
  const visualTab = dialog.getByRole('tab', { name: 'Visual Diff' })
  await expect(visualTab).toBeEnabled({ timeout: 15_000 })
  await visualTab.click()

  const renderedPage = dialog.getByRole('region', { name: 'Rendered diff page 1' })
  await expect(renderedPage).toBeVisible({ timeout: 30_000 })
  await expect(renderedPage.getByLabel('Visual pixel differences for page 1')).toBeVisible()
  await expect(renderedPage).toContainText(/\d[\d,]* changed pixels/)
  await expect(dialog.getByText('Added ink')).toBeVisible()
  await expect(dialog.getByText('Removed ink')).toBeVisible()
})
