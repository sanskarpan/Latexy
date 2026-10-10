/** Benchmark the current span projection against shipped templates. No app boot. */
import { createRequire } from 'node:module'
import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import vm from 'node:vm'
import { performance } from 'node:perf_hooks'
import { createHash } from 'node:crypto'

const root = fileURLToPath(new URL('../../../', import.meta.url))
const require = createRequire(path.join(root, 'frontend/package.json'))
const ts = require('typescript')
const sourcePath = path.join(root, 'frontend/src/lib/wysiwyg/visual-projection.ts')
const source = readFileSync(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const context = { exports: {} }
vm.runInNewContext(compiled, context, { filename: sourcePath, timeout: 1000 })
const project = context.exports.projectVisualResume
function files(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(folder, entry.name)
    return entry.isDirectory() ? files(full) : full.endsWith('.tex') ? [full] : []
  })
}
const median = values => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)]
const p95 = values => [...values].sort((a, b) => a - b)[Math.ceil(values.length * 0.95) - 1]
const round = value => Math.round(value * 10000) / 10000
const all = []
const templates = files(path.join(root, 'backend/app/data/templates')).sort().map(file => {
  const input = readFileSync(file, 'utf8')
  project(input)
  const samples = []
  for (let index = 0; index < 100; index++) {
    const start = performance.now()
    project(input)
    samples.push(performance.now() - start)
  }
  all.push(...samples)
  const projection = project(input)
  return {
    path: path.relative(root, file).replaceAll('\\', '/'),
    fields: projection.fields.length,
    unsupportedBlocks: projection.unsupportedBlocks,
    p50_ms: round(median(samples)), p95_ms: round(p95(samples)),
  }
})
const output = {
  scope: 'Node microbenchmark of current projection; excludes React, browser layout, PDF rendering and network',
  node: process.version,
  source_sha256: createHash('sha256').update(source).digest('hex'),
  calls: all.length, templates: templates.length,
  p50_ms: round(median(all)), p95_ms: round(p95(all)),
  template_results: templates,
}
writeFileSync(new URL('./visual-measurements.json', import.meta.url), JSON.stringify(output, null, 2) + '\n')
console.log(JSON.stringify({ ...output, template_results: undefined }, null, 2))
