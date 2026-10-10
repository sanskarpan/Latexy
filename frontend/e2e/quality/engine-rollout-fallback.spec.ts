import { expect, test, type Page } from '@playwright/test'
import { mockEngineAncillaryApi, readMonacoSource } from './engine-fixtures'

const source = '\\documentclass{article}\n\\begin{document}\nMy preserved resume\n\\end{document}'
const owner = { session: { token: 'rollout-owner-token' }, user: { id: 'rollout-owner', email: 'rollout@example.com', name: 'Rollout Owner' } }

function legacyPdf() {
  const content = 'BT /F1 10 Tf 40 740 Td (My preserved resume) Tj ET'
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${content.length} >>\nstream\n${content}\nendstream`]
  let pdf = '%PDF-1.4\n'; const offsets = [0]
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${object}\nendobj\n` })
  const start = Buffer.byteLength(pdf)
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`
  return Buffer.from(pdf)
}

async function base(page: Page, authenticated = false) {
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockEngineAncillaryApi(page, owner.user.id)
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: authenticated ? owner : null }))
  await page.route('**/public/trial-status**', route => route.fulfill({ json: { usageCount: 0, remainingUses: 3, blocked: false, canUse: true, trialLimit: 3 } }))
  await page.routeWebSocket('**/ws/jobs**', socket => socket.close())
  await page.addInitScript(source => {
    localStorage.setItem('latexy_try_latex', source)
    localStorage.setItem('latexy_auto_compile', 'false')
  }, source)
}

for (const scenario of ['404', 'missing-version', 'future-version'] as const) {
  test(`guest ${scenario} deployment preserves source without repeated engine requests`, async ({ page }) => {
    await base(page)
    let probes = 0; let engineCalls = 0; let mutations = 0
    await page.route('**/public/engine/capabilities', route => {
      probes++
      return route.fulfill({ status: scenario === '404' ? 404 : 200, json: scenario === 'future-version' ? { resume_engine_version: 2 } : {} })
    })
    await page.route('**/public/engine/document**', route => { engineCalls++; return route.fulfill({ status: 404, json: {} }) })
    await page.route('**/jobs/submit', route => { mutations++; return route.fulfill({ status: 500, json: {} }) })
    await page.goto('/try')
    await expect(page.getByText('Resume fields are not available on this server yet.', { exact: false })).toBeVisible()
    await expect.poll(() => readMonacoSource(page)).toBe(source)
    await expect(page.getByRole('button', { name: 'Resume', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Source', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await page.evaluate(value => (window as typeof window & { __latexyMonacoEditor?: { setValue(value: string): void } }).__latexyMonacoEditor?.setValue(value), source + '\n% new local edit')
    await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_try_latex'))).toBe(source + '\n% new local edit')
    expect(await page.evaluate(() => localStorage.getItem('latexy_auto_compile'))).toBe('false')
    expect({ probes, engineCalls, mutations }).toEqual({ probes: 1, engineCalls: 0, mutations: 0 })
    if (scenario === '404') {
      let pdfRequests = 0
      await page.route('**/jobs/submit', route => {
        mutations++
        expect(route.request().postDataJSON().latex_content).toBe(source + '\n% new local edit')
        return route.fulfill({ json: { success: true, job_id: 'legacy-rollout-pdf', message: 'Queued' } })
      })
      await page.route('**/jobs/legacy-rollout-pdf/state', route => route.fulfill({ json: { job_id: 'legacy-rollout-pdf', status: 'completed', stage: 'completed', percent: 100, last_updated: Date.now() / 1000 } }))
      await page.route('**/jobs/legacy-rollout-pdf/result', route => route.fulfill({ json: { job_id: 'legacy-rollout-pdf', success: true, pdf_job_id: 'legacy-rollout-pdf', page_count: 1 } }))
      await page.route('**/download/legacy-rollout-pdf', route => { pdfRequests++; return route.fulfill({ contentType: 'application/pdf', body: legacyPdf() }) })
      await page.route('**/download/legacy-rollout-pdf/synctex', route => route.fulfill({ status: 404 }))
      await page.getByRole('button', { name: 'Recompile', exact: true }).click()
      await expect(page.locator('.react-pdf__Page canvas').first()).toBeVisible({ timeout: 30000 })
      expect(pdfRequests).toBe(1)
      expect(mutations).toBe(1)
      expect(engineCalls).toBe(0)
    }
  })
}

for (const status of [401, 403]) {
  test(`capability ${status} stays an authorization error and retries only explicitly`, async ({ page }) => {
    await base(page)
    let supported = false; let probes = 0; let engineCalls = 0
    await page.route('**/public/engine/capabilities', route => { probes++; return route.fulfill({ status: supported ? 200 : status, json: supported ? { resume_engine_version: 1 } : {} }) })
    await page.route('**/public/engine/document**', route => { engineCalls++; return route.fulfill({ status: 403, json: {} }) })
    await page.goto('/try')
    await expect(page.getByText('Access to resume fields could not be verified.', { exact: false })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Source', exact: true })).toHaveAttribute('aria-pressed', 'false')
    await expect(page.locator('.monaco-editor')).toHaveCount(0)
    await page.getByRole('button', { name: 'Source', exact: true }).click()
    await expect.poll(() => readMonacoSource(page)).toBe(source)
    expect(probes).toBe(1)
    supported = true
    await page.getByRole('button', { name: 'Retry resume fields' }).click()
    await expect(page.getByRole('button', { name: 'Resume', exact: true })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Source', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect({ probes, engineCalls }).toEqual({ probes: 2, engineCalls: 0 })
  })
}

test('saved editor capability fallback preserves its stored mode and unsaved buffer', async ({ page }) => {
  const resumeId = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
  await base(page, true)
  await page.addInitScript(id => localStorage.setItem(`latexy_editor_mode_${id}`, 'pdf'), resumeId)
  let engineCalls = 0; let denyRetry = false
  await page.route('**/public/engine/capabilities', route => route.fulfill({ status: denyRetry ? 403 : 404, json: {} }))
  await page.route(`**/resumes/${resumeId}`, route => route.fulfill({ json: { id: resumeId, user_id: owner.user.id, title: 'Preserved resume', latex_content: source, document_type: 'resume', metadata: {}, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' } }))
  await page.route(`**/resumes/${resumeId}/engine/**`, route => { engineCalls++; return route.fulfill({ status: 404, json: {} }) })
  await page.goto(`/workspace/${resumeId}/edit`)
  await expect(page.getByText('Resume fields are not available on this server yet.', { exact: false })).toBeVisible()
  await expect.poll(() => readMonacoSource(page)).toBe(source)
  await page.evaluate(value => (window as typeof window & { __latexyMonacoEditor?: { setValue(value: string): void } }).__latexyMonacoEditor?.setValue(value), source + '\n% unsaved local edit')
  denyRetry = true
  await page.getByRole('button', { name: 'Retry resume fields' }).click()
  await expect(page.getByText('Access to resume fields could not be verified.', { exact: false })).toBeVisible()
  await expect.poll(() => readMonacoSource(page)).toBe(source + '\n% unsaved local edit')
  expect(await page.evaluate(id => localStorage.getItem(`latexy_editor_mode_${id}`), resumeId)).toBe('pdf')
  expect(engineCalls).toBe(0)
})

test('unavailable PDF import preserves selected file and title without uploading or paid conversion', async ({ page }) => {
  await base(page, true)
  let mutations = 0
  await page.route('**/public/engine/capabilities', route => route.fulfill({ status: 404, json: {} }))
  await page.route('**/resumes/imports/pdf', route => { mutations++; return route.fulfill({ status: 404, json: {} }) })
  await page.route('**/formats/upload**', route => { mutations++; return route.fulfill({ status: 500, json: {} }) })
  await page.goto('/workspace/new')
  await page.getByLabel('Resume Title', { exact: true }).fill('Keep this title')
  await page.getByRole('button', { name: /Import File/ }).click()
  await page.locator('input[type=file]').setInputFiles({ name: 'preserved.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nsynthetic selected file') })
  await expect(page.getByText('PDF import is not available on this server yet.', { exact: false })).toBeVisible()
  await expect(page.getByText('Selected file: preserved.pdf')).toBeVisible()
  await expect(page.getByLabel('Resume Title', { exact: true })).toHaveValue('Keep this title')
  expect(mutations).toBe(0)
  await page.getByRole('button', { name: 'Choose another file' }).click()
  await expect(page.locator('input[type=file]')).toHaveCount(1)
})
