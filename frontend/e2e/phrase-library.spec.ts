import { expect, test } from '@playwright/test'

const RESUME_ID = '11111111-1111-4111-8111-111111111111'
const LATEX = String.raw`\documentclass{article}
\begin{document}
\begin{itemize}
  \item Built APIs for a payments platform.
\end{itemize}
\end{document}`
const PHRASE = String.raw`Engineered distributed services that improved throughput by [X]\% for critical payment workflows.`

test('role-indexed phrase library shows signals and inserts a non-fabricated placeholder', async ({ page }) => {
  let phraseRequest: Record<string, unknown> | null = null
  let savedLatex: string | null = null
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token')
    localStorage.setItem('latexy_onboarding_completed', 'true')
  })
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { id: 'session-1', userId: 'user-1', token: 'test-token' },
      user: { id: 'user-1', email: 'user@example.com', name: 'Taylor' },
    }),
  }))
  await page.routeWebSocket('**/ws/**', (socket) => socket.close())
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"tenant":null}',
  }))
  await page.route((url) => ['/config/feature-flags', '/config/entitlements'].includes(url.pathname), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/academic-cv-report`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }),
  }))
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: '[]',
  }))
  await page.route((url) => url.pathname === '/ats/quick-score', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ score: 75, grade: 'C', sections_found: [], missing_sections: [] }),
  }))
  await page.route((url) => url.pathname === '/jobs/submit', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, job_id: 'compile-1', message: 'Started' }),
  }))
  await page.route((url) => url.pathname === '/ai/phrase-library', async (route) => {
    phraseRequest = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_title: 'Platform Engineer', seniority: 'senior', industry: 'Fintech',
        skill_category: 'Distributed systems', cached: false,
        phrases: Array.from({ length: 10 }, (_, index) => ({
          text: index === 0 ? PHRASE : `Led adaptable platform initiative ${String.fromCharCode(65 + index)} with truthful [X] impact.`,
          signals: index === 0 ? ['technical_depth', 'high_impact'] : ['ats_friendly'],
        })),
      }),
    })
  })
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, async (route) => {
    if (route.request().method() === 'PUT') {
      savedLatex = route.request().postDataJSON().latex_content
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: RESUME_ID, user_id: 'user-1', title: 'Platform Resume',
        latex_content: savedLatex ?? LATEX, document_type: 'resume',
        created_at: '2026-09-14T00:00:00Z', updated_at: '2026-09-14T00:00:00Z',
      }),
    })
  })

  await page.goto(`/workspace/${RESUME_ID}/edit`)
  await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
  await expect.poll(() => page.evaluate(() => {
    return (window as typeof window & {
      __latexyMonacoEditor?: { getValue(): string }
    }).__latexyMonacoEditor?.getValue()
  }), { timeout: 30_000 }).toBe(LATEX)
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __latexyMonacoEditor?: {
        focus(): void
        setPosition(position: { lineNumber: number; column: number }): void
      }
    }).__latexyMonacoEditor
    if (!editor) throw new Error('Monaco test editor is unavailable')
    // The inline AI control exists only on an actual \item line.
    editor.setPosition({ lineNumber: 4, column: 1 })
    editor.focus()
  })
  await page.getByTitle('AI Bullet Generator').click()
  await page.getByRole('tab', { name: 'Phrase library' }).click()
  await page.getByLabel('Job title').fill('Platform Engineer')
  await page.getByLabel('Seniority').selectOption('senior')
  await page.getByLabel('Industry').fill('Fintech')
  await page.getByLabel('Skill category').fill('Distributed systems')
  await page.getByRole('button', { name: 'Browse 10 phrases' }).click()

  await expect.poll(() => phraseRequest).not.toBeNull()
  expect(phraseRequest).toMatchObject({
    job_title: 'Platform Engineer', seniority: 'senior', industry: 'Fintech',
    skill_category: 'Distributed systems', count: 10,
  })
  await expect(page.getByText('Technical depth')).toBeVisible()
  await expect(page.getByText('High impact')).toBeVisible()
  await page.getByRole('button', { name: new RegExp('Engineered distributed services') }).click()
  await expect.poll(() => savedLatex, { timeout: 10_000 }).toContain('[X]\\%')
})
