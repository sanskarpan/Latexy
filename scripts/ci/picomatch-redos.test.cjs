'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..', '..')
const versions = ['2.3.2', '4.0.7']

// Resolve the exact patched copy used by consumers. The pnpm store also keeps
// the unpatched tarball directory; the `_patch_hash` directory is the one the
// lockfile wires into every dependent, so that is the copy under test.
function load(version) {
  const store = path.join(root, 'node_modules', '.pnpm')
  const prefix = `picomatch@${version}_patch_hash=`
  const matches = fs.readdirSync(store).filter((name) => name.startsWith(prefix))
  assert.equal(
    matches.length,
    1,
    `expected exactly one patched picomatch@${version} install, found ${matches.length}`,
  )
  const dir = path.join(store, matches[0], 'node_modules', 'picomatch')
  assert.ok(fs.existsSync(dir), `patched picomatch@${version} is missing`)
  const manifest = require(path.join(dir, 'package.json'))
  assert.equal(manifest.version, version)
  return require(dir)
}

for (const version of versions) {
  const pm = load(version)

  // GHSA-fc5q-39xc-vjpf: a repeated single-branch extglob with a top-level
  // wildcard must not backtrack exponentially. The unpatched `+(*a)` takes
  // seconds on this short non-matching input; the patched parser rejects the
  // risky shape before it can build the ambiguous regex.
  const adversarial = 'a'.repeat(28) + 'b'
  const started = process.hrtime.bigint()
  const matched = pm('+(*a)')(adversarial)
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6
  assert.equal(matched, false, `picomatch@${version} unexpectedly matched`)
  assert.ok(
    elapsedMs < 1000,
    `picomatch@${version} ReDoS guard was too slow: ${elapsedMs.toFixed(1)}ms`,
  )

  // The mitigation must not break ordinary extglob matching.
  assert.equal(pm('+(a|b)')('abba'), true, `picomatch@${version} +(a|b)`)
  assert.equal(pm('+(foo)')('foofoo'), true, `picomatch@${version} +(foo)`)
  assert.equal(pm('+(*)')('abc'), true, `picomatch@${version} +(*)`)
  assert.equal(pm('+([a-z])')('abc'), true, `picomatch@${version} +([a-z])`)
}
