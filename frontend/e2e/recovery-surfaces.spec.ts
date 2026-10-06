import { test, expect, type Page } from '@playwright/test'

const DEEP_JOB_ID = 'deep-recovery-job'

async function openDeepRecovery(page: Page, mode: 'healthy' | 'unavailable' | 'failed' = 'healthy'): Promise<() => number> {
  let resultReads = 0
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session: null, user: null }),
    }))
  await page.route((url) => url.pathname === '/config/feature-flags', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ trial_limits: false, deep_analysis_trial: true, compile_timeouts: true, task_priority: true, billing: true, upgrade_ctas: false }),
    }))
  await page.route((url) => url.pathname === '/public/trial-status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ usageCount: 0, remainingUses: 3, blocked: false, canUse: true }),
    }))
  await page.route((url) => url.pathname === '/ats/quick-score', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ score: 72, grade: 'B', sections_found: ['experience'], missing_sections: [], keyword_match_percent: 62 }),
    }))
  await page.route((url) => url.pathname === '/ats/deep-analyze', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: DEEP_JOB_ID, uses_remaining: 2, message: 'Started' }),
    }))
  await page.route((url) => url.pathname === `/jobs/${DEEP_JOB_ID}/state`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: mode === 'failed' ? 'failed' : 'completed', stage: '', percent: 100, last_updated: Date.now() / 1000 }),
    }))
  await page.route((url) => url.pathname === `/jobs/${DEEP_JOB_ID}/result`, (route) => {
    resultReads += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mode === 'unavailable' ? {
        success: false,
        job_id: DEEP_JOB_ID,
        error: 'Completed job output unavailable',
        result: {
          success: false,
          job_id: DEEP_JOB_ID,
          recovery_complete: false,
          error_code: 'output_unavailable',
          omitted_output_fields: ['deep_analysis'],
        },
      } : {
        success: true,
        job_id: DEEP_JOB_ID,
        result: {
          success: true,
          job_id: DEEP_JOB_ID,
          pdf_job_id: null,
          tokens_used: 44,
          deep_analysis: {
            overall_score: 91,
            overall_feedback: 'Strong match after REST recovery',
            sections: [{
              name: 'Experience',
              score: 88,
              strengths: ['Clear ownership'],
              improvements: ['Add dates'],
            }],
            ats_compatibility: { score: 90, issues: [], keyword_gaps: [] },
            job_match: null,
            tokens_used: 44,
            analysis_time: 1.2,
            multi_dim_scores: {
              grammar: 92,
              bullet_clarity: 86,
              section_completeness: 84,
              page_density: 78,
              keyword_density: 74,
            },
            industry_key: 'tech_saas',
            industry_label: 'Technology / SaaS',
          },
        },
      }),
    })
  })
  // This case deliberately misses the typed deep event; the REST poll is the
  // only source of the analysis payload.
  await page.route('**/ws/**', (route) => route.abort())

  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('button[title="ATS Score"]').first()).toBeVisible({ timeout: 20_000 })
  await page.locator('button[title="ATS Score"]').first().click()
  await expect(page.getByRole('button', { name: 'Deep scan' })).toBeVisible()
  await page.getByRole('button', { name: 'Deep scan' }).click()
  return () => resultReads
}

test('deep ATS REST recovery hydrates sections, radar scores, and industry after missed events', async ({ page }) => {
  await openDeepRecovery(page)
  await expect(page.getByText('Overall ATS Score')).toBeVisible({ timeout: 20_000 })
  const dialog = page.getByRole('dialog', { name: 'Deep AI Analysis' })
  await expect(dialog.getByText('Strong match after REST recovery')).toBeVisible()
  await expect(dialog.getByText('Experience')).toBeVisible()
  await expect(dialog.getByText('Add dates')).toBeVisible()
  await expect(dialog.getByText('Technology / SaaS')).toBeVisible()
  await expect(dialog.locator('span').filter({ hasText: /^Grammar$/ }).last()).toBeVisible()
  await expect(dialog.locator('svg path[stroke="#8b5cf6"]').first()).toBeVisible()
})

test('deep ATS incomplete durable output displays a delivery error and stops polling', async ({ page }) => {
  const resultReads = await openDeepRecovery(page, 'unavailable')
  const dialog = page.getByRole('dialog', { name: 'Deep AI Analysis' })
  await expect(dialog.getByText('Job completed, but its generated output is unavailable.', { exact: true })).toBeVisible({ timeout: 20_000 })
  await expect(dialog.getByText('Overall ATS Score')).toHaveCount(0)
  expect(resultReads()).toBe(1)
  // Drain more than one normal 4s poll period: this is a permanent delivery
  // error, not a missing result that should silently retry for ten minutes.
  await page.waitForTimeout(4_500)
  expect(resultReads()).toBe(1)
})

test('deep ATS worker failure is visible rather than returning to the empty analysis screen', async ({ page }) => {
  const resultReads = await openDeepRecovery(page, 'failed')
  const dialog = page.getByRole('dialog', { name: 'Deep AI Analysis' })
  await expect(dialog.getByText('Analysis failed', { exact: true })).toBeVisible({ timeout: 20_000 })
  await expect(dialog.getByText('Job failed', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Overall ATS Score')).toHaveCount(0)
  expect(resultReads()).toBe(0)
})
