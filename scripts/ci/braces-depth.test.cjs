'use strict'

const assert = require('node:assert/strict')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const repoRoot = path.resolve(__dirname, '..', '..')
const frontendRoot = path.join(repoRoot, 'frontend')

// Resolve through a real frontend consumer. Do not use a top-level `require
// ('braces')`: braces is transitive here, and this makes the test fail closed
// if the patched dependency is absent from the installed graph.
const eslintEntry = require.resolve('eslint', { paths: [frontendRoot] })
const bracesEntry = require.resolve('braces', { paths: [path.dirname(eslintEntry)] })
const bracesPackage = require(path.join(path.dirname(bracesEntry), 'package.json'))
const braces = require(bracesEntry)

assert.equal(bracesPackage.name, 'braces')
assert.equal(bracesPackage.version, '3.0.3')

const SAFE_DEPTH = 127
const LIMIT = 128
const ERROR_NAME = 'RangeError'
const ERROR_MESSAGE = 'Brace nesting exceeds safe depth'

function nested(open, close, depth) {
  return open.repeat(depth) + 'x' + close.repeat(depth)
}

function directAst(depth) {
  const root = { type: 'root', nodes: [] }
  let parent = root
  for (let index = 0; index < depth; index += 1) {
    const child = { type: 'text', nodes: [], parent }
    parent.nodes = [child]
    parent = child
  }
  parent.nodes = [{ type: 'text', value: 'x', parent }]
  return root
}

function assertThrowsCustom(label, fn) {
  assert.throws(fn, error => {
    assert.equal(error.name, ERROR_NAME, label)
    assert.equal(error.message, ERROR_MESSAGE, label)
    assert.ok(!/call stack|stack overflow/i.test(error.message), label)
    return true
  }, label)
}

// Keep ordinary behavior covered: alternatives, ranges, invalid escapes, and
// AST stringification all remain unchanged at normal depths.
assert.deepEqual(braces.expand('file-{1..3}.js'), ['file-1.js', 'file-2.js', 'file-3.js'])
assert.equal(braces.compile('a/{b,c}/d'), 'a/(b|c)/d')
assert.deepEqual(braces.expand('literal\\{x\\}'), ['literal{x}'])
assert.equal(braces.stringify(braces.parse('a/{b,c}')), 'a/{b,c}')
assert.equal(braces.compile('{a,b', { escapeInvalid: true }), '\\{a,b')
assert.equal(braces.compile(braces.parse('a/{b,c}')), 'a/(b|c)')
assert.deepEqual(braces.expand(braces.parse('a/{b,c}')), ['a/b', 'a/c'])
assert.equal(braces.stringify(braces.parse('a/{b,c}')), 'a/{b,c}')

// The parser accepts the last safe level for both brace and parenthesis
// nesting; all recursive walkers must then process that AST without crashing.
for (const [label, input] of [
  ['curly', nested('{', '}', SAFE_DEPTH)],
  ['parentheses', nested('(', ')', SAFE_DEPTH)],
]) {
  assert.doesNotThrow(() => braces.parse(input), `${label} parse at safe depth`)
  assert.doesNotThrow(() => braces.compile(input), `${label} compile at safe depth`)
  assert.doesNotThrow(() => braces.expand(input), `${label} expand at safe depth`)
  assert.doesNotThrow(() => braces.stringify(input), `${label} stringify at safe depth`)
}

// Exercise compile/expand/stringify directly with caller-supplied ASTs, which
// bypass parsing and therefore need their own recursion guard.
for (const [label, operation] of [
  ['compile', ast => braces.compile(ast)],
  ['expand', ast => braces.expand(ast)],
  ['stringify', ast => braces.stringify(ast)],
]) {
  assert.doesNotThrow(() => operation(directAst(SAFE_DEPTH)), `${label} direct AST at safe depth`)
  assertThrowsCustom(`${label} direct AST over depth`, () => operation(directAst(LIMIT + 1)))
}

function childCall(operation, input) {
  const source = `
    const braces = require(${JSON.stringify(bracesEntry)});
    const input = ${JSON.stringify(input)};
    const operation = ${JSON.stringify(operation)};
    try {
      let value;
      if (operation === 'parse') value = braces.parse(input);
      else if (operation === 'compile') value = braces.compile(input);
      else if (operation === 'expand') value = braces.expand(input);
      else if (operation === 'stringify') value = braces.stringify(input);
      else throw new Error('unknown operation');
      process.stdout.write(JSON.stringify({ ok: true, value }));
    } catch (error) {
      process.stdout.write(JSON.stringify({ ok: false, name: error.name, message: error.message }));
    }
  `
  return spawnSync(process.execPath, ['-e', source], {
    cwd: repoRoot,
    encoding: 'utf8',
    timeout: 2500,
    maxBuffer: 1024 * 1024,
  })
}

function childDirectAstCall(operation, depth) {
  const source = `
    const braces = require(${JSON.stringify(bracesEntry)});
    const depth = ${depth};
    const root = { type: 'root', nodes: [] };
    let parent = root;
    for (let index = 0; index < depth; index += 1) {
      const child = { type: 'text', nodes: [], parent };
      parent.nodes = [child];
      parent = child;
    }
    parent.nodes = [{ type: 'text', value: 'x', parent }];
    try {
      const value = braces.${operation}(root);
      process.stdout.write(JSON.stringify({ ok: true, value }));
    } catch (error) {
      process.stdout.write(JSON.stringify({ ok: false, name: error.name, message: error.message }));
    }
  `
  return spawnSync(process.execPath, ['-e', source], {
    cwd: repoRoot,
    encoding: 'utf8',
    timeout: 2500,
    maxBuffer: 1024 * 1024,
  })
}

function assertChildBounded(label, operation, input) {
  const result = childCall(operation, input)
  assert.equal(result.error, undefined, `${label} timed out or failed to spawn`)
  assert.equal(result.status, 0, `${label} crashed: ${result.stderr}`)
  const output = JSON.parse(result.stdout)
  assert.equal(output.ok, false, `${label} was accepted instead of rejected`)
  assert.equal(output.name, ERROR_NAME, `${label} error type`)
  assert.equal(output.message, ERROR_MESSAGE, `${label} error message`)
  assert.ok(!/call stack|stack overflow/i.test(result.stderr), `${label} emitted stack-overflow diagnostics`)
}

// Fresh processes ensure a pre-patch stack overflow cannot take down the test
// runner. These include balanced and unbalanced curly/parenthesis inputs and
// every public recursive operation.
const bombs = [
  ['balanced curly', nested('{', '}', LIMIT + 1)],
  ['unbalanced curly', '{'.repeat(LIMIT + 1)],
  ['balanced parentheses', nested('(', ')', LIMIT + 1)],
  ['unbalanced parentheses', '('.repeat(LIMIT + 1)],
]
for (const [label, input] of bombs) {
  for (const operation of ['parse', 'compile', 'expand', 'stringify']) {
    assertChildBounded(`${label} ${operation}`, operation, input)
  }
}

// A much larger payload confirms the guard is bounded in wall time and does
// not merely move the failure to V8's generic maximum-call-stack error.
for (const [label, input] of [
  ['large curly bomb', '{'.repeat(10000)],
  ['large parentheses bomb', '('.repeat(10000)],
]) {
  for (const operation of ['parse', 'compile', 'expand', 'stringify']) {
    assertChildBounded(`${label} ${operation}`, operation, input)
  }
}

for (const operation of ['compile', 'expand', 'stringify']) {
  const result = childDirectAstCall(operation, LIMIT + 1)
  assert.equal(result.error, undefined, `direct AST ${operation} timed out or failed to spawn`)
  assert.equal(result.status, 0, `direct AST ${operation} crashed: ${result.stderr}`)
  const output = JSON.parse(result.stdout)
  assert.equal(output.ok, false, `direct AST ${operation} was accepted instead of rejected`)
  assert.equal(output.name, ERROR_NAME, `direct AST ${operation} error type`)
  assert.equal(output.message, ERROR_MESSAGE, `direct AST ${operation} error message`)
}

console.log(`braces ${bracesPackage.version}: depth, malformed-input, direct-AST, and compatibility checks passed`)
