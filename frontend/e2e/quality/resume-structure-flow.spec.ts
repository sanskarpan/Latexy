import { expect, test } from './quality-test'
import { createHash } from 'node:crypto'
import { mockEngineAncillaryApi } from './engine-fixtures'

if (process.env.ENGINE_QA_CHROME === '1') test.use({ channel: 'chrome' })
const digest = (value: string | Buffer) => createHash('sha256').update(value).digest('hex')
function pdfRows(rows: string[]) {
  const content = rows.map((text, index) => `BT /F1 10 Tf 40 ${752 - index * 20} Td (${text}) Tj ET`).join('\n')
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>', `<< /Length ${content.length} >>\nstream\n${content}\nendstream`]
  let pdf = '%PDF-1.4\n'; const offsets = [0]
  objects.forEach((value, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${value}\nendobj\n` })
  const start = Buffer.byteLength(pdf)
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`
  return Buffer.from(pdf)
}

test('managed PDF edits headings and moves stable sections, entries and bullets with CAS', async ({ page }) => {
  test.setTimeout(240000)
  const resumeId = '88888888-8888-8888-8888-888888888888'
  let revision = 1; let heading = 'Experience'
  let sections = ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests']
  let entries = ['entry-a', 'entry-b']; let bullets = ['bullet-a', 'bullet-b']
  const texts: Record<string, string> = { 'bullet-a': 'Built internal tools', 'bullet-b': 'Mentored four engineers', 'bullet-c': 'Improved testing coverage' }
  const source = () => '\\documentclass{article}\n\\begin{document}\n' + sections.flatMap((section) => section === 'experience'
    ? [`\\section*{${heading}}`, ...entries.flatMap((entry) => [entry === 'entry-a' ? 'Company A' : 'Company B', '\\begin{itemize}',
      ...(entry === 'entry-a' ? bullets : ['bullet-c']).map((id) => '\\item ' + texts[id]), '\\end{itemize}'])]
    : section === 'education' ? ['\\section*{Education}', 'University'] : []).join('\n') + '\n\\end{document}'
  const rows = (latex: string) => latex.split('\n').flatMap((line) => line.startsWith('\\section*{') ? [line.slice(10, -1)]
    : line.startsWith('\\item ') ? [line.slice(6)] : ['Company A', 'Company B', 'University'].includes(line) ? [line] : [])
  const document = (latex = source(), rev = revision) => {
    const node = (id: string, section: string, kind: string, text: string, containerId: string, child: string, entryId?: string) => ({
      node_id: id, section, kind, text, node_revision: digest(id + '\0' + text), editable: true, ai_editable: kind === 'bullet',
      source_span: { start: latex.indexOf(text), end: latex.indexOf(text) + text.length }, container_id: containerId, order_child_id: child, entry_id: entryId,
    })
    const currentHeading = latex.match(/\\section\*\{([^}]*Experience[^}]*)\}/)?.[1] ?? heading
    return { document_id: resumeId, source_mode: 'managed', content_revision: rev, source_sha256: digest(latex), structured_version: 1, template_id: 'managed', opaque_blocks: [],
      nodes: [node('section.experience.heading', 'experience', 'section_heading', currentHeading, 'sections', 'experience'),
        node('section.education.heading', 'education', 'section_heading', 'Education', 'sections', 'education'),
        ...Object.entries(texts).map(([id, text]) => node(id, 'experience', 'bullet', text, `section.experience.entry.${id === 'bullet-c' ? 'entry-b' : 'entry-a'}.bullets`, id, id === 'bullet-c' ? 'entry-b' : 'entry-a'))],
      containers: [{ container_id: 'sections', kind: 'sections', label: 'Sections', ordered_child_ids: sections, node_ids: ['section.experience.heading', 'section.education.heading'] },
        { container_id: 'section.experience.entries', kind: 'entries', section: 'experience', parent_id: 'sections', label: heading, ordered_child_ids: entries, node_ids: Object.keys(texts) },
        { container_id: 'section.experience.entry.entry-a.bullets', kind: 'bullets', section: 'experience', entry_id: 'entry-a', parent_id: 'section.experience.entries', label: 'Bullets', ordered_child_ids: bullets, node_ids: ['bullet-a', 'bullet-b'] },
        { container_id: 'section.experience.entry.entry-b.bullets', kind: 'bullets', section: 'experience', entry_id: 'entry-b', parent_id: 'section.experience.entries', label: 'Bullets', ordered_child_ids: ['bullet-c'], node_ids: ['bullet-c'] }] }
  }
  const jobs = new Map<string, { source: string; document: ReturnType<typeof document>; pdf: Buffer }>()
  const commands: Record<string, unknown>[] = []
  const artifacts = (id: string) => {
    const job = jobs.get(id)!
    return { type: 'artifact.ready', job_id: id, artifact_id: digest(id), source_sha256: digest(job.source), content_revision: job.document.content_revision,
      document_id: resumeId, branch: 'draft', owner_epoch: 1, pdf_sha256: digest(job.pdf), pdf_size: job.pdf.length, page_count: 1,
      compiler: 'pdflatex', settings_sha256: digest('settings'), preview_url: `/download/${id}/preview/${digest(id)}`, geometry_url: `/download/${id}/preview/${digest(id)}/geometry` }
  }
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: { session: { token: 'contract-owner-token' }, user: { id: 'structure-owner', email: 'owner@example.com', name: 'Owner' } } }))
  await mockEngineAncillaryApi(page, 'structure-owner')
  await page.route('**/macros', route => route.fulfill({ json: [] }))
  await page.route(`**/resumes/${resumeId}`, route => route.fulfill({ json: { id: resumeId, user_id: 'structure-owner', title: 'Structured resume', latex_content: source(), document_type: 'resume', metadata: {}, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' } }))
  await page.route(`**/resumes/${resumeId}/engine/import`, route => route.fulfill({ status: 404, json: { detail: 'No original upload' } }))
  await page.route(`**/resumes/${resumeId}/engine/document`, async route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      expect(body.expected_content_revision).toBe(revision); expect(body.expected_source_sha256).toBe(digest(source()))
      expect(body.patches[0].node_id).toBe('section.experience.heading')
      expect(body.patches[0].expected_node_revision).toBe(digest('section.experience.heading\0' + heading))
      heading = body.patches[0].text; revision++
    }
    await route.fulfill({ json: { document: document(), latex_content: source() } })
  })
  await page.route(`**/resumes/${resumeId}/engine/structure`, async route => {
    const body = route.request().postDataJSON(); commands.push(body)
    expect(body.expected_content_revision).toBe(revision); expect(body.expected_source_sha256).toBe(digest(source()))
    const before = body.container_id === 'sections' ? sections : body.container_id === 'section.experience.entries' ? entries : bullets
    expect([...body.ordered_ids].sort()).toEqual([...before].sort())
    if (body.container_id === 'sections') sections = body.ordered_ids
    else if (body.container_id === 'section.experience.entries') entries = body.ordered_ids
    else bullets = body.ordered_ids
    revision++
    await route.fulfill({ json: { document: document(), latex_content: source() } })
  })
  await page.route('**/jobs/submit', async route => {
    const latex = route.request().postDataJSON().latex_content; const id = `structure-${jobs.size + 1}`
    jobs.set(id, { source: latex, document: document(latex), pdf: pdfRows(rows(latex)) })
    await route.fulfill({ json: { success: true, job_id: id } })
  })
  await page.route('**/jobs/*/state', route => {
    const id = new URL(route.request().url()).pathname.split('/')[2]
    return route.fulfill({ json: { status: 'completed', stage: '', percent: 100, artifact: artifacts(id), last_updated: Date.now() / 1000 } })
  })
  await page.route('**/jobs/*/result', route => {
    const id = new URL(route.request().url()).pathname.split('/')[2]
    return route.fulfill({ json: { success: true, job_id: id, result: { success: true, job_id: id, pdf_job_id: id, compilation_time: .01 } } })
  })
  await page.route('**/download/*/preview/*', route => route.fulfill({ contentType: 'application/pdf', body: jobs.get(new URL(route.request().url()).pathname.split('/')[2])!.pdf }))
  await page.route('**/download/*/preview/*/geometry', route => {
    const id = new URL(route.request().url()).pathname.split('/')[2], job = jobs.get(id)!, artifact = artifacts(id), lines = rows(job.source)
    return route.fulfill({ json: { schema_version: 1, coordinate_system: 'pdf_points_top_left', artifact_id: artifact.artifact_id, document_id: resumeId,
      content_revision: job.document.content_revision, branch: 'draft', source_sha256: artifact.source_sha256, pdf_sha256: artifact.pdf_sha256,
      pages: [{ page: 1, width: 612, height: 792, rotation: 0 }], boxes: job.document.nodes.map((node) => ({ ...node, page: 1, x: 40, y: 30 + lines.indexOf(node.text) * 20, width: node.text.length * 6, height: 14 })) } })
  })
  await page.routeWebSocket('**/ws/jobs**', socket => socket.close())
  await page.goto(`/workspace/${resumeId}/edit`)
  await expect.poll(() => jobs.size).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Preview', exact: true }).click()
  await page.getByRole('button', { name: 'Edit resume field: Experience', exact: true }).click()
  await page.getByLabel('experience · section heading', { exact: true }).fill('Professional Experience')
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect.poll(() => heading).toBe('Professional Experience')
  await expect(page.getByRole('button', { name: 'Edit resume field: Professional Experience', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Move section down', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(sections.indexOf('experience')).toBeGreaterThan(sections.indexOf('education'))
  await expect.poll(() => [...jobs.values()].slice(-1)[0]?.source).toBe(source())
  await expect(page.getByRole('button', { name: 'Edit resume field: Built internal tools', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Edit resume field: Built internal tools', exact: true }).click()
  await page.getByRole('button', { name: 'Move item down', exact: true }).click()
  await expect.poll(() => commands.length).toBe(2); expect(bullets).toEqual(['bullet-b', 'bullet-a'])
  await expect(page.getByRole('button', { name: 'Move entry down', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Move entry down', exact: true }).click()
  await expect.poll(() => commands.length).toBe(3); expect(entries).toEqual(['entry-b', 'entry-a'])
  await expect.poll(() => [...jobs.values()].slice(-1)[0]?.source).toBe(source())
  await expect(page.getByRole('button', { name: 'Edit resume field: Built internal tools', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Move entry up', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect.poll(() => commands.length).toBe(4); expect(entries).toEqual(['entry-a', 'entry-b'])
  await expect(page.locator('.monaco-editor')).toHaveCount(0)
})
