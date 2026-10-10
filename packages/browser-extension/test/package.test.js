import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('the CI archive includes every local popup module dependency', () => {
  const popup = readFileSync(new URL('../popup.js', import.meta.url), 'utf8')
  const workflow = readFileSync(new URL('../../../.github/workflows/ci.yml', import.meta.url), 'utf8')
  const archive = workflow.match(/zip -r \.\.\/\.\.\/latexy-browser-extension\.zip\s+([\s\S]*?)\n\s+- name:/)?.[1]
  assert.ok(archive, 'The extension archive step must be declared')
  const entries = new Set(archive.trim().split(/\s+/))
  const imports = [...popup.matchAll(/from ['"]\.\/([^'"]+)['"]/g)].map((match) => match[1])
  assert.ok(imports.includes('capabilities.js'))
  for (const path of imports) assert.ok(entries.has(path), `Archive omits popup dependency: ${path}`)
})
