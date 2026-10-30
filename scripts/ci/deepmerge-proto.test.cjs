'use strict'

const assert = require('node:assert/strict')
const path = require('node:path')

const repoRoot = path.resolve(__dirname, '..', '..')
const frontendRoot = path.join(repoRoot, 'frontend')

// Resolve through a real frontend consumer chain. Do not use a top-level
// `require('deepmerge')`: deepmerge is transitive here (next-pwa ->
// workbox-build -> @rollup/plugin-node-resolve -> deepmerge), and this makes
// the test fail closed if the patched dependency is absent from the installed
// graph or the chain changes shape.
const nextPwaEntry = require.resolve('@ducanh2912/next-pwa', { paths: [frontendRoot] })
const workboxEntry = require.resolve('workbox-build', { paths: [path.dirname(nextPwaEntry)] })
const pluginEntry = require.resolve('@rollup/plugin-node-resolve', { paths: [path.dirname(workboxEntry)] })
const deepmergeEntry = require.resolve('deepmerge', { paths: [path.dirname(pluginEntry)] })
const deepmergePackage = require(path.resolve(path.dirname(deepmergeEntry), '..', 'package.json'))
const deepmerge = require(deepmergeEntry)

assert.equal(deepmergePackage.name, 'deepmerge')
assert.equal(deepmergePackage.version, '4.3.1')

function mergePoisoned(parseTarget, parseSource) {
  const result = deepmerge(JSON.parse(parseTarget), JSON.parse(parseSource))
  const noLeak = result.polluted === undefined
  const protoIntact = Object.getPrototypeOf(result) === Object.prototype
  const globalClean = ({}).polluted === undefined && Object.prototype.polluted === undefined
  delete Object.prototype.polluted
  return { noLeak, protoIntact, globalClean }
}

// GHSA-gcqx-w48m-w2h4: a source parsed from JSON carries '__proto__' as an
// own enumerable key. On the unpatched build this replaces the fresh
// destination object's prototype with attacker-controlled data, so
// `result.polluted` reads `true` through the poisoned prototype even though
// `Object.prototype` itself is untouched.
{
  const { noLeak, protoIntact, globalClean } = mergePoisoned('{}', '{"__proto__": {"polluted": true}}')
  assert.equal(noLeak, true, 'source-side __proto__ must not surface on the merged result')
  assert.equal(protoIntact, true, 'merged result must keep Object.prototype')
  assert.equal(globalClean, true, 'Object.prototype must stay clean')
}

// Same guard for the target side: a target parsed from JSON can carry its own
// '__proto__' property, which the pre-patch guard treated as mergeable and
// then assigned onto the destination, poisoning it the same way.
{
  const { noLeak, protoIntact, globalClean } = mergePoisoned(
    '{"__proto__": {"seed": 1}}',
    '{"__proto__": {"polluted": true}}',
  )
  assert.equal(noLeak, true, 'target-side __proto__ must not surface on the merged result')
  assert.equal(protoIntact, true, 'merged result must keep Object.prototype')
  assert.equal(globalClean, true, 'Object.prototype must stay clean')
}

// Keep ordinary behavior covered: shallow merge, nested merge, array concat,
// scalar overwrite and cloning all remain unchanged.
assert.deepEqual(deepmerge({ a: 1 }, { b: 2 }), { a: 1, b: 2 })
assert.deepEqual(deepmerge({ a: { x: 1 } }, { a: { y: 2 } }), { a: { x: 1, y: 2 } })
assert.deepEqual(deepmerge({ list: [1] }, { list: [2] }), { list: [1, 2] })
assert.deepEqual(deepmerge({ a: 1 }, { a: 2 }), { a: 2 })
assert.deepEqual(deepmerge({ nested: { deep: { v: 1 } } }, { nested: { deep: { w: 2 } } }),
  { nested: { deep: { v: 1, w: 2 } } })
const merged = deepmerge({ a: { x: 1 } }, { a: { y: 2 } })
assert.notEqual(merged.a, undefined)
assert.deepEqual(merged.a, { x: 1, y: 2 })
