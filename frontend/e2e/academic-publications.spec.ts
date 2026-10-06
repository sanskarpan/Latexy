import { expect, test } from '@playwright/test'

const PUBLICATION_SECTION = String.raw`\section{Publications}
\begin{enumerate}
  \item Doe, J. (2025). Safe Systems. Journal of Testing.
\end{enumerate}`
const RESUME_ID = '123e4567-e89b-42d3-a456-426614174000'

test('ORCID publications normalize URLs, apply citation style, invalidate stale filters, and insert', async ({ page }) => {
  await page.route('**/api/auth/get-session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { token: 'mock-token' },
      user: { id: 'academic-user', email: 'academic@example.com', name: 'Academic User' },
    }),
  }))
  await page.route((url) => url.pathname === '/config/feature-flags', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ trial_limits: true }),
  }))
  await page.route((url) => url.pathname === '/public/trial-status', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ usageCount: 0, trialLimit: 3, blocked: false }),
  }))
  await page.route((url) => url.pathname === '/ats/quick-score', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ score: 75, grade: 'C', sections_found: [], missing_sections: [] }),
  }))
  await page.route((url) => url.pathname.startsWith('/analytics'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{}',
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: 'academic-user',
      title: 'Academic CV',
      latex_content: String.raw`\documentclass{article}\begin{document}CV\end{document}`,
      document_type: 'academic_cv',
      metadata: { compiler: 'pdflatex' },
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/academic-cv-report`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ is_academic_cv: true, detected_sections: ['publications'], estimated_pages: 3, confidence: 0.9 }),
  }))

  const requests: Array<Record<string, unknown>> = []
  await page.route((url) => url.pathname === '/ai/generate-publications', async route => {
    requests.push(JSON.parse(route.request().postData() ?? '{}'))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        publications: [{
          title: 'Safe Systems',
          authors: ['Jane Doe'],
          venue: 'Journal of Testing',
          year: 2025,
          doi: '10.1000/safe',
          url: 'https://doi.org/10.1000/safe',
          pub_type: 'journal',
          latex_entry: 'Doe, J. (2025). Safe Systems. Journal of Testing.',
        }],
        latex_section: PUBLICATION_SECTION,
        cached: false,
      }),
    })
  })

  await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Academic CV').first()).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Publications', exact: true }).click()

  await page.getByLabel('ORCID iD').fill('https://orcid.org/0000-0001-2345-6789/')
  await page.getByRole('radio', { name: /APA/ }).check()
  await page.getByRole('button', { name: 'Fetch Publications' }).click()

  await expect(page.getByText('Safe Systems')).toBeVisible()
  expect(requests[0]).toMatchObject({
    identifier: '0000-0001-2345-6789',
    citation_style: 'apa',
  })

  // A changed filter invalidates the old response; it must not remain insertable.
  await page.getByLabel('Publication year from').fill('2024')
  await expect(page.getByText('Safe Systems')).toBeHidden()
  await expect(page.getByRole('button', { name: /Insert Publications Section/ })).toHaveCount(0)

  await page.getByRole('button', { name: 'Fetch Publications' }).click()
  await page.getByRole('button', { name: 'Insert Publications Section (1)' }).click()
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
  ).__latexyMonacoEditor?.getValue().replace(/\r\n/g, '\n'))).toContain(PUBLICATION_SECTION)
  expect(requests[1]).toMatchObject({ year_from: 2024, citation_style: 'apa' })
})
