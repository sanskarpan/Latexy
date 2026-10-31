'use strict'

const assert = require('node:assert/strict')
const path = require('node:path')

const frontendRoot = path.resolve(__dirname, '..', '..', 'frontend')

// Resolve through the real consumer chain, one hop at a time. Do not require
// 'minimatch' from the repo root: it is transitive everywhere here, and this
// makes the test fail closed if the dependency graph changes shape.
function resolveThrough(names) {
  let dir = frontendRoot
  let entry
  for (const name of names) {
    entry = require.resolve(name, { paths: [dir] })
    dir = path.dirname(entry)
  }
  return entry
}

function packageOf(entry) {
  // Walk up to the owning package root: dist/commonjs/index.js nests two
  // levels deep while minimatch.js sits at the root.
  let dir = path.dirname(entry)
  for (;;) {
    try {
      const manifest = require(path.join(dir, 'package.json'))
      if (manifest && manifest.name === 'minimatch') return manifest
    } catch {}
    const parent = path.dirname(dir)
    assert.notEqual(parent, dir, `no minimatch package root above ${entry}`)
    dir = parent
  }
}

// GHSA-g3hv-75wg-m249: '**/..' portions double the pattern sets on every
// split in the optimizer, so 30 innocent-looking segments become ~1e9 sets
// and exhaust memory. Each segment below is identical on purpose.
const ADVERSARIAL = Array(30).fill('**/../a/b').join('/')

// --- minimatch 10.2.6: the installed copy must carry the backported cap ---
const mm10Entry = resolveThrough([
  '@typescript-eslint/parser',
  '@typescript-eslint/typescript-estree',
  'minimatch',
])
assert.equal(packageOf(mm10Entry).name, 'minimatch')
assert.equal(packageOf(mm10Entry).version, '10.2.6')
const { Minimatch } = require(mm10Entry)

// Splits stop at the configured cap instead of doubling without bound.
assert.equal(
  new Minimatch(ADVERSARIAL, { optimizationLevel: 2, braceExpandMax: 64 }).set.length,
  64,
)
// Default options complete and stop at the default cap (pre-patch: OOM).
assert.equal(new Minimatch(ADVERSARIAL, { optimizationLevel: 2 }).set.length, 100000)
// Matching behavior is preserved, including the dedupe-skip path (>1000 sets).
{
  const small = new Minimatch('**/../a/b/**/../c/d', { optimizationLevel: 2 })
  assert.equal(small.set.length, 4)
  assert.equal(small.match('../a/b/../c/d'), true)
  assert.equal(small.match('x/a/b/y/c/d'), true)
  const large = new Minimatch('{x,*}/{0..999}', { optimizationLevel: 2 })
  assert.equal(large.set.length, 2000)
  assert.equal(large.match('x/5'), true)
  assert.equal(large.match('y/999'), true)
  assert.equal(large.match('.y/5'), false)
}

// --- minimatch 5.1.9: the vulnerable optimizer does not exist here ---
const mm5Entry = resolveThrough([
  '@ducanh2912/next-pwa',
  'workbox-build',
  '@surma/rollup-plugin-off-main-thread',
  'ejs',
  'jake',
  'filelist',
  'minimatch',
])
assert.equal(packageOf(mm5Entry).name, 'minimatch')
assert.equal(packageOf(mm5Entry).version, '5.1.9')
const mm5 = require(mm5Entry)

// No **/.. splitting transform exists in this engine, so the adversarial
// pattern stays a single set instead of doubling per segment.
assert.equal(new mm5.Minimatch(Array(25).fill('**/../a/b').join('/')).set.length, 1)
assert.equal(mm5('foo/bar', 'foo/*'), true)
assert.equal(mm5('foo/bar', 'foo/*.js'), false)

// --- minimatch 3.1.5: same engine generation, same structural guarantee ---
const mm3Entry = resolveThrough(['eslint', 'minimatch'])
assert.equal(packageOf(mm3Entry).name, 'minimatch')
assert.equal(packageOf(mm3Entry).version, '3.1.5')
const mm3 = require(mm3Entry)
assert.equal(new mm3.Minimatch(Array(25).fill('**/../a/b').join('/')).set.length, 1)
assert.equal(mm3('foo/bar', 'foo/*'), true)
assert.equal(mm3('foo/bar', 'foo/*.js'), false)
