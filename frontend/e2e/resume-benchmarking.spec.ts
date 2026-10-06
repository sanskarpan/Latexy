import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = '123e4567-e89b-42d3-a456-426614174034'
const JOB_ID = 'benchmark-compile-job'
const LATEX = '\\documentclass{article}\n\\begin{document}\nA benchmark resume with enough source text to initialize compilation and render the complete optimization workspace.\\end{document}'

async function mockPage(page: Page) {
  await page.route('**/api/auth/get-session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { token: 'benchmark-token' },
      user: { id: 'benchmark-user', email: 'benchmark@example.com', name: 'Benchmark User' },
    }),
  }))
  await page.route((url) => url.pathname === '/ws/ticket', route => route.fulfill({
    status: 201, contentType: 'application/json', body: '{"ticket":"benchmark-ticket","expires_in":30}',
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: 'benchmark-user',
      title: 'Benchmark Resume',
      latex_content: LATEX,
      metadata: {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    }),
  }))
  await page.route((url) => url.pathname.includes('/checkpoints'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '[]',
  }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{"is_academic_cv":false,"detected_sections":[],"estimated_pages":1,"confidence":0}',
  }))
  await page.route((url) => url.pathname === '/jobs/submit', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, job_id: JOB_ID, message: 'Started' }),
  }))
  await page.route((url) => url.pathname === '/ats/quick-score', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{"score":60,"grade":"C","sections_found":[],"missing_sections":[]}',
  }))
  await page.route((url) => url.pathname.endsWith('/ats/industry-profiles'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"profiles":[]}',
  }))
  await page.route((url) => url.pathname.startsWith('/analytics'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{}',
  }))
  await page.route((url) => /\/jobs\/[^/]+\/state$/.test(url.pathname), route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{"status":"queued","stage":"","percent":0,"last_updated":1}',
  }))

  let sequence = 0
  await page.routeWebSocket('**/ws/jobs**', ws => {
    ws.onMessage(data => {
      const message = JSON.parse(data as string)
      if (message.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
      }
      if (message.type === 'subscribe' && message.job_id === JOB_ID) {
        ws.send(JSON.stringify({ type: 'subscribed', job_id: JOB_ID, replayed_count: 0 }))
        setTimeout(() => ws.send(JSON.stringify({
          type: 'event',
          event: {
            event_id: 'benchmark-completed',
            job_id: JOB_ID,
            timestamp: Date.now() / 1000,
            sequence: ++sequence,
            type: 'job.completed',
            pdf_job_id: JOB_ID,
            ats_score: 60,
            ats_details: { category_scores: {}, recommendations: [], warnings: [], strengths: [] },
            changes_made: [],
            compilation_time: 1,
            optimization_time: 0,
            tokens_used: 0,
            page_count: 1,
          },
        })), 50)
      }
    })
  })
}

test('benchmark is honest, actionable, and ignores a stale score response', async ({ page }) => {
  await mockPage(page)
  const requestedScores: number[] = []
  await page.route((url) => url.pathname === '/ats/benchmark', async route => {
    const score = Number(new URL(route.request().url()).searchParams.get('ats_score'))
    requestedScores.push(score)
    if (score === 60) await new Promise(resolve => setTimeout(resolve, 700))
    const percentile = score === 90 ? 95 : 50
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        percentile,
        sample_size: 500,
        cohort_median: 65,
        cohort_p25: 50,
        cohort_p75: 80,
        industry: 'general',
        sufficient_data: true,
        cohort_label: 'Latexy resume cohort',
        methodology: 'Latest scored optimization per distinct resume',
      }),
    })
  })
  await page.route((url) => url.pathname === '/ats/score', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      ats_score: 90,
      category_scores: {},
      recommendations: ['Add a measurable outcome'],
      warnings: [],
      strengths: [],
      industry_key: 'finance_banking',
      industry_label: 'Finance',
    }),
  }))

  await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Community Benchmark')).toBeVisible({ timeout: 30_000 })
  await page.getByTitle('Override industry calibration').selectOption('finance_banking')

  await expect(page.getByText('top 5%')).toBeVisible()
  await expect(page.getByText(/Latexy resume cohort/)).toBeVisible()
  await expect(page.getByText(/Directional comparison only—not hiring odds/)).toBeVisible()
  await expect(page.getByText(/Latest scored optimization per distinct resume/)).toBeVisible()
  await page.waitForTimeout(800)
  await expect(page.getByText('top 50%')).toHaveCount(0)
  expect(requestedScores).toEqual(expect.arrayContaining([60, 90]))
})
