import { expect, test } from '@playwright/test'
const leaves = ['d14_latex', 'd14_table_text', 'd14_table_image', 'd14_math_text', 'd14_math_image'] as const
const paths = ['/ai/generate-latex', '/ai/generate-table', '/ai/generate-table-image', '/ai/generate-math', '/ai/generate-math-image']

// Actual HTTP to the complete backend router; auth/policy are controlled
// synthetic fixtures. PostgreSQL-backed auth/migration acceptance is separate.
test('isolated actual HTTP denies all leaves and ancestors for every account role', async ({ request }) => {
  const base = process.env.D14_HTTP_BACKEND_URL
  test.skip(!base, 'Requires the explicit loopback-only D14 backend fixture')
  const url = new URL(base!)
  expect(['localhost', '127.0.0.1', '::1']).toContain(url.hostname)
  for (const role of ['user', 'support', 'admin']) for (const denied of ['leaf', 'd14', 'ai_writing']) for (const axis of ['global', 'role', 'family', 'sku']) {
    for (const [index, leaf] of leaves.entries()) {
      const configured = await request.post(`${base}/__test/policy`, { data: { role, denied_key: denied === 'leaf' ? leaf : denied, axis } })
      expect(configured.ok()).toBeTruthy()
      const response = await request.post(`${base}${paths[index]}`, leaf.endsWith('image')
        ? { multipart: { file: { name: 'sample.png', mimeType: 'image/png', buffer: Buffer.from('89504e470d0a1a0a', 'hex') } } }
        : { data: leaf === 'd14_latex' ? { intent: 'Create a heading' } : leaf.includes('table') ? { table_text: 'A,B\n1,2' } : { math_text: 'x squared' } })
      expect(response.status(), await response.text()).toBe(403)
      expect(await response.text()).toContain('feature_disabled')
    }
  }
  const evidence = await request.get(`${base}/__test/evidence`)
  expect(evidence.ok()).toBeTruthy()
  expect((await evidence.json()).handler_effects).toBe(0)
})
