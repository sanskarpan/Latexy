import { expect, test } from '@playwright/test'

const RESUME_ID = 'a9234567-e89b-42d3-a456-426614174032'
const JOB_ID = 'native-share-fixture-job'
const PDF_ID = 'native-share-fixture-pdf'

type ShareProbe = typeof window & {
  __shareCalls?: number
  __finishShare?: (name: string) => void
  __shareSettled?: boolean
  __downloadClicks?: string[]
  __latexyMonacoEditor?: { getValue(): string }
}

test.describe('editor native PDF share fallback ownership', () => {
  for (const scenario of ['same-owner failure', 'owner-switch failure', 'same-owner cancellation'] as const) {
    test(scenario, async ({ page }) => {
      test.skip(process.env.PWA_PRODUCTION !== '1', 'requires the reviewed production editor bundle')
      let owner = 'native-owner-a'
      let sessionCalls = 0
      let pdfDownloads = 0
      const browserDownloads: string[] = []
      page.on('download', (download) => browserDownloads.push(download.suggestedFilename()))

      await page.addInitScript(() => {
        const probe = window as ShareProbe
        probe.__shareCalls = 0
        probe.__shareSettled = false
        probe.__downloadClicks = []
        const click = HTMLAnchorElement.prototype.click
        HTMLAnchorElement.prototype.click = function () {
          if (this.download) probe.__downloadClicks?.push(this.download)
          click.call(this)
        }
        Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => true })
        Object.defineProperty(navigator, 'share', {
          configurable: true,
          value: () => {
            probe.__shareCalls = (probe.__shareCalls ?? 0) + 1
            return new Promise<void>((_resolve, reject) => {
              probe.__finishShare = (name) => {
                reject(new DOMException('Controlled native share outcome', name))
                setTimeout(() => { probe.__shareSettled = true }, 0)
              }
            })
          },
        })
      })
      await page.route('**/api/auth/get-session', (route) => {
        sessionCalls += 1
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
          session: { token: `token-${owner}` }, user: { id: owner, email: `${owner}@example.com`, name: owner },
        }) })
      })
      await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify({
          id: RESUME_ID, user_id: owner, title: `Native Share ${owner}`,
          latex_content: `\\documentclass{article}\\begin{document}${owner} source.\\end{document}`,
          document_type: 'resume', metadata: {}, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
        }),
      }))
      await page.route((url) => url.pathname.includes('/checkpoints'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
      await page.route((url) => url.pathname.endsWith('/academic-cv-report'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"is_academic_cv":false,"detected_sections":[]}' }))
      await page.route('**/github/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"private_sync":false}' }))
      await page.route('**/dropbox/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"connected":false}' }))
      await page.route((url) => url.pathname.startsWith('/analytics') || ['/trial/status', '/resumes/stats', '/me'].includes(url.pathname), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
      await page.route((url) => url.pathname === '/ats/quick-score', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"score":70,"grade":"C","sections_found":[],"missing_sections":[]}' }))
      await page.route((url) => url.pathname === '/jobs/submit', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_ID }) }))
      await page.route((url) => url.pathname === `/jobs/${JOB_ID}/state`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"completed"}' }))
      await page.route((url) => url.pathname === `/jobs/${JOB_ID}/result`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_ID, result: { success: true, pdf_job_id: PDF_ID } }) }))
      await page.route((url) => url.pathname.endsWith(`/download/${PDF_ID}`), (route) => {
        pdfDownloads += 1
        return route.fulfill({ status: 200, contentType: 'application/pdf', body: Buffer.from('%PDF-1.7\nNative share fixture\n%%EOF') })
      })
      await page.route('**/ws/ticket', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"ticket":"native-share-ticket"}' }))
      await page.routeWebSocket('**/ws/jobs**', (ws) => ws.onMessage((data) => {
        const message = JSON.parse(data as string) as { type?: string; job_id?: string }
        if (message.type !== 'subscribe' || message.job_id !== JOB_ID) return
        ws.send(JSON.stringify({ type: 'subscribed', job_id: JOB_ID, replayed_count: 0 }))
        ws.send(JSON.stringify({ type: 'event', stream_id: '9999999999999-0', event: {
          type: 'job.completed', event_id: 'native-share-complete', job_id: JOB_ID, timestamp: Date.now() / 1000,
          sequence: 1, pdf_job_id: PDF_ID, ats_score: null, ats_details: null, changes_made: [],
          compilation_time: 0, optimization_time: 0, tokens_used: 0, page_count: 1,
        } }))
      }))

      await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeVisible({ timeout: 30_000 })
      await page.getByRole('button', { name: 'Compile', exact: true }).click()
      await expect.poll(() => pdfDownloads).toBe(1)
      await page.getByRole('button', { name: 'Share', exact: true }).click()
      await expect.poll(() => page.evaluate(() => (window as ShareProbe).__shareCalls)).toBe(1)

      if (scenario === 'owner-switch failure') {
        owner = 'native-owner-b'
        await page.evaluate(() => {
          const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
          localStorage.setItem('better-auth.message', message)
          window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
        })
        await expect.poll(() => sessionCalls).toBeGreaterThan(1)
        await expect.poll(() => page.evaluate(() => (window as ShareProbe).__latexyMonacoEditor?.getValue())).toContain('native-owner-b source')
      }
      await page.evaluate((name) => (window as ShareProbe).__finishShare?.(name), scenario === 'same-owner cancellation' ? 'AbortError' : 'NotAllowedError')
      await expect.poll(() => page.evaluate(() => (window as ShareProbe).__shareSettled)).toBe(true)
      const clicks = await page.evaluate(() => (window as ShareProbe).__downloadClicks)
      if (scenario === 'same-owner failure') {
        expect(clicks).toEqual(['Native_Share_native-owner-a.pdf'])
        await expect.poll(() => browserDownloads).toEqual(['Native_Share_native-owner-a.pdf'])
      } else {
        expect(clicks).toEqual([])
        expect(browserDownloads).toEqual([])
      }
      await expect(page.getByText('Sharing or downloading the PDF failed. Retry when storage or network access is available.', { exact: true })).toHaveCount(0)
    })
  }
})
