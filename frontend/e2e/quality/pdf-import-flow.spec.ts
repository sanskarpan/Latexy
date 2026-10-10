import { expect, test } from '@playwright/test'
import { createHash } from 'node:crypto'
import { mockEngineAncillaryApi } from './engine-fixtures'

if (process.env.ENGINE_QA_CHROME === '1') test.use({ channel: 'chrome' })
const digest = (value: string | Buffer) => createHash('sha256').update(value).digest('hex')
function originalPdf() {
  const text = 'BT /F1 12 Tf 40 740 Td (Original resume appearance) Tj ET'
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${text.length} >>\nstream\n${text}\nendstream`]
  let pdf = '%PDF-1.4\n'; const offsets = [0]
  objects.forEach((value, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${value}\nendobj\n` })
  const start = Buffer.byteLength(pdf)
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`
  return Buffer.from(pdf)
}

for (const scenario of ['review', 'mismatch', 'manual']) test(scenario === 'mismatch'
  ? 'PDF import refuses a receipt for different original bytes'
  : scenario === 'manual' ? 'PDF import keeps unavailable extraction explicit and accepts user supplied details'
  : 'PDF import preserves the original and explicitly adapts reviewed fields', async ({ page }) => {
  test.setTimeout(240000)
  const mismatch = scenario === 'mismatch'
  const extractedName = scenario === 'manual' ? '' : 'Original Name'
  const pdf = originalPdf()
  const resumeId = '77777777-7777-7777-7777-777777777777'
  const source = '\\documentclass{article}\n\\begin{document}\nReviewed Name\n\\end{document}'
  const document = { document_id: resumeId, source_mode: 'managed', content_revision: 1, source_sha256: digest(source),
    structured_version: 1, template_id: 'supported-template', nodes: [{ node_id: 'basics.name', node_revision: digest('basics.name\0Reviewed Name'),
      section: 'basics', kind: 'field', text: 'Reviewed Name', editable: true, ai_editable: false,
      source_span: { start: source.indexOf('Reviewed Name'), end: source.indexOf('Reviewed Name') + 'Reviewed Name'.length } }], opaque_blocks: [], containers: [] }
  const receipt = { import_id: 'contract-import', original: { filename: 'original.pdf', mime_type: 'application/pdf', size_bytes: pdf.length,
    sha256: mismatch ? digest('different PDF') : digest(pdf), preview_url: '/resumes/imports/contract-import/original' },
    extraction: { status: scenario === 'manual' ? 'unavailable' : 'partial', warnings: ['Compare extracted text with the original PDF.'], fields: [
      { field_id: 'basics.name', node_revision: digest('basics.name\0' + extractedName), label: 'Name', text: extractedName, confidence: 'unknown', warnings: [] },
    ] }, supported_templates: [{ template_id: 'supported-template', name: 'Clean resume', category: 'professional' }], expires_at: '2026-10-08T00:00:00Z' }
  const adaptations: Record<string, unknown>[] = []; let conversions = 0; let originalRequests = 0
  // WebKit's intercepted multipart postDataBuffer omits file bytes. Observe
  // the actual FormData given to fetch, then let the application send it.
  await page.addInitScript(() => {
    const originalFetch = window.fetch
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href)
      if (url.pathname === '/resumes/imports/pdf' && init?.body instanceof FormData) {
        const file = init.body.get('file')
        if (file instanceof File) {
          ;(window as typeof window & { uploadedPdfBytes?: number[] }).uploadedPdfBytes = Array.from(new Uint8Array(await file.arrayBuffer()))
        }
      }
      return originalFetch.call(window, input, init)
    }
  })
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: { session: { token: 'contract-owner-token' },
    user: { id: 'import-owner', email: 'import-owner@example.com', name: 'Import Owner' } } }))
  await mockEngineAncillaryApi(page, 'import-owner')
  await page.route('**/formats/upload**', route => { conversions++; return route.fulfill({ status: 500, json: { detail: 'Paid conversion is outside this flow' } }) })
  await page.route('**/resumes/imports/pdf', async route => {
    expect(route.request().headers().authorization).toBe('Bearer contract-owner-token')
    expect(route.request().headers()['content-type']).toContain('multipart/form-data')
    const uploaded = await page.evaluate(() => (window as typeof window & { uploadedPdfBytes?: number[] }).uploadedPdfBytes)
    expect(Buffer.from(uploaded ?? [])).toEqual(pdf)
    await route.fulfill({ json: receipt })
  })
  await page.route('**/resumes/imports/contract-import/original', route => {
    originalRequests++; expect(route.request().headers().authorization).toBe('Bearer contract-owner-token')
    return route.fulfill({ contentType: 'application/pdf', body: pdf })
  })
  await page.route('**/resumes/imports/contract-import/adapt', async route => {
    adaptations.push(route.request().postDataJSON())
    await route.fulfill({ json: { resume_id: resumeId, document, latex_content: source, original: receipt.original } })
  })
  await page.route(`**/resumes/${resumeId}`, route => route.fulfill({ json: { id: resumeId, user_id: 'import-owner', title: 'Imported resume',
    latex_content: source, document_type: 'resume', metadata: {}, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' } }))
  await page.route(`**/resumes/${resumeId}/engine/document`, route => route.fulfill({ json: { document, latex_content: source } }))
  await page.route(`**/resumes/${resumeId}/engine/import`, route => route.fulfill({ json: { ...receipt, resume_id: resumeId, expires_at: null } }))
  await page.route('**/macros', route => route.fulfill({ json: [] }))
  await page.routeWebSocket('**/ws/jobs**', socket => socket.close())
  // Compile the editor route separately so its cold development compilation
  // does not consume the navigation assertion's normal interaction timeout.
  if (!mismatch) await page.request.get(`/workspace/${resumeId}/edit`)
  await page.goto('/workspace/new')
  await page.locator('#new-resume-title').fill('Imported resume')
  await page.getByRole('button', { name: /Import File/ }).click()
  await page.locator('input[type="file"]').setInputFiles({ name: 'original.pdf', mimeType: 'application/pdf', buffer: pdf })
  const wizard = page.getByRole('region', { name: 'Review PDF import' })
  await expect(wizard).toBeVisible()
  if (mismatch) {
    await expect(wizard.getByRole('alert')).toContainText('does not match the file you selected')
    expect(originalRequests).toBe(0); expect(adaptations).toHaveLength(0)
  } else {
    await expect(wizard.locator('.react-pdf__Page canvas')).toBeVisible()
    await expect(wizard.getByText('Extraction confidence: unknown', { exact: true })).toBeVisible()
    await expect(wizard.getByRole('button', { name: 'Create editable resume' })).toBeDisabled()
    await wizard.getByLabel('Name', { exact: true }).fill('Reviewed Name')
    await wizard.getByLabel('Editable layout', { exact: true }).selectOption('supported-template')
    await expect(wizard.getByRole('button', { name: 'Create editable resume' })).toBeEnabled()
    await wizard.getByRole('button', { name: 'Create editable resume' }).click()
    await expect.poll(() => adaptations.length).toBe(1)
    expect(adaptations[0]).toEqual({ title: 'Imported resume', template_id: 'supported-template', expected_original_sha256: digest(pdf),
      field_edits: [{ node_id: 'basics.name', expected_node_revision: digest('basics.name\0' + extractedName), text: 'Reviewed Name' }] })
    await expect(page).toHaveURL(new RegExp(`/workspace/${resumeId}/edit`))
    await page.getByRole('button', { name: 'Original PDF', exact: true }).click()
    const attachment = page.getByRole('dialog', { name: 'Original uploaded PDF' })
    await expect(attachment.locator('.react-pdf__Page canvas')).toBeVisible()
    await expect(attachment.getByText('Original upload · read-only', { exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(attachment).toHaveCount(0)
  }
  expect(conversions).toBe(0)
})
