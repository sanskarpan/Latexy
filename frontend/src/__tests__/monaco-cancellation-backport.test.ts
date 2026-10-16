import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { MONACO_BACKPORT, sha256, verifyMonacoCancellationBackport } from '../../scripts/monaco-cancellation-backport.mjs'
import { fingerprintMonacoAssets, prepareMonaco } from '../../scripts/prepare-monaco.mjs'

const require = createRequire(import.meta.url)
const vendorRoot = path.dirname(require.resolve('monaco-editor/package.json'))
const root = mkdtempSync(path.join(os.tmpdir(), 'latexy-monaco-backport-'))
const patchedRoot = path.join(root, 'patched')
const originals = new Map<string, string>()
const patched = new Map<string, string>()
const patchPath = fileURLToPath(new URL('../../../patches/monaco-editor@0.55.1.patch', import.meta.url))

// Apply the committed pnpm patch to exact original bytes in a disposable copy.
// Never patch the current dependency installation (which may be shared).
for (const [relative, integrity] of Object.entries(MONACO_BACKPORT.files) as Array<[string, { original: string; patched: string }]>) {
  const destination = path.join(patchedRoot, relative)
  mkdirSync(path.dirname(destination), { recursive: true })
  const installed = readFileSync(path.join(vendorRoot, relative), 'utf8')
  const digest = sha256(installed)
  if (digest !== integrity.original && digest !== integrity.patched) throw new Error(`Unexpected Monaco source: ${relative}`)
  writeFileSync(destination, installed)
}
const esmPath = 'esm/vs/editor/contrib/wordHighlighter/browser/wordHighlighter.js'
const amdPath = 'min/vs/editor.api-CalNCsUg.js'
if (sha256(readFileSync(path.join(patchedRoot, esmPath))) === MONACO_BACKPORT.files[esmPath].patched) {
  execFileSync('git', ['-c', 'core.autocrlf=false', 'apply', '--reverse', patchPath], { cwd: patchedRoot })
}
for (const relative of Object.keys(MONACO_BACKPORT.files)) originals.set(relative, readFileSync(path.join(patchedRoot, relative), 'utf8'))
execFileSync('git', ['-c', 'core.autocrlf=false', 'apply', patchPath], { cwd: patchedRoot })
for (const relative of Object.keys(MONACO_BACKPORT.files)) patched.set(relative, readFileSync(path.join(patchedRoot, relative), 'utf8'))
copyFileSync(path.join(vendorRoot, 'package.json'), path.join(patchedRoot, 'package.json'))
afterAll(() => rmSync(root, { recursive: true, force: true }))

function nodes(source: string) {
  const file = ts.createSourceFile('vendor.js', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const result: ts.Node[] = []
  function visit(node: ts.Node) { result.push(node); ts.forEachChild(node, visit) }
  visit(file)
  return result
}

function declaration(all: ts.Node[], name: string) {
  const node = all.find(node => (
    (ts.isClassDeclaration(node) || ts.isFunctionDeclaration(node) || ts.isVariableDeclaration(node))
    && node.name?.getText() === name
  ))
  if (!node) throw new Error(`Missing vendor declaration: ${name}`)
  return ts.isVariableDeclaration(node) ? `const ${node.getText()};` : node.getText()
}

function probeSource(format: 'esm' | 'amd', source: string) {
  const all = nodes(source)
  const highlighter = all.find(node => (
    (ts.isClassDeclaration(node) || ts.isClassExpression(node))
    && node.members.some(member => ts.isConstructorDeclaration(member) && member.getText().includes('this.runDelayer'))
  )) as ts.ClassExpression
  if (!highlighter) throw new Error('Missing actual WordHighlighter class')
  const classNodes = nodes(highlighter.getText())
  const callback = (event: string) => {
    const call = classNodes.find(node => ts.isCallExpression(node)
      && ts.isPropertyAccessExpression(node.expression)
      && node.expression.name.text === event) as ts.CallExpression
    if (!call || call.arguments.length !== 1) throw new Error(`Missing vendor callback: ${event}`)
    return call.arguments[0].getText()
  }
  const method = (name: string) => {
    const member = highlighter.members.find(member => ts.isMethodDeclaration(member) && member.name.getText() === name) as ts.MethodDeclaration
    if (!member?.body) throw new Error(`Missing vendor method: ${name}`)
    return `function(${member.parameters.map(parameter => parameter.getText()).join(',')})${member.body.getText()}`
  }
  let runtime: string
  let delayer: string
  let handler: string
  if (format === 'esm') {
    const asyncNodes = nodes(readFileSync(path.join(vendorRoot, 'esm/vs/base/common/async.js'), 'utf8'))
    const errorNodes = nodes(readFileSync(path.join(vendorRoot, 'esm/vs/base/common/errors.js'), 'utf8'))
    runtime = ['timeoutDeferred', 'microtaskDeferred', 'Delayer'].map(name => declaration(asyncNodes, name)).join('\n')
      + '\n' + ['ErrorHandler', 'errorHandler', 'canceledName', 'CancellationError', 'isCancellationError', 'onUnexpectedError'].map(name => declaration(errorNodes, name)).join('\n')
      + "\nconst MicrotaskDelay = Symbol('MicrotaskDelay');"
    delayer = 'Delayer'; handler = 'errorHandler'
  } else {
    runtime = ['rne', 'ane', 'pr', 'wie', 'hR', 'ty', 'hr', 'To', 'De', '_6'].map(name => declaration(all, name)).join('\n')
    delayer = 'pr'; handler = 'hR'
  }
  // Run extracted real callbacks, methods, Delayer and cancellation handler in
  // a child process. Its rejection listener observes the causal red control;
  // no rejection handler is attached to the promises under test by the harness.
  return `
    ${runtime}
    const unhandled = [], surfaced = [];
    process.on('unhandledRejection', error => unhandled.push({ name: error.name, message: error.message }));
    ${handler}.unexpectedErrorHandler = error => surfaced.push(error.message);
    const makeCursor = function() { return ${callback('onDidChangeCursorPosition')}; };
    const makeFocus = function() { return ${callback('onDidFocusEditorText')}; };
    const restore = ${method('restore')};
    const dispose = ${method('dispose')};
    const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
    const outcomes = [];
    for (const mode of ['cursor', 'focus', 'restore']) {
      function fixture(realError) {
        const runDelayer = new ${delayer}(50);
        return { runDelayer, occurrencesHighlightEnablement: 'singleFile', workerRequest: null,
          _ignorePositionChangeEvent: false,
          _onPositionChanged() { if (realError) throw new Error('genuine-' + mode); },
          _run() { if (realError) throw new Error('genuine-' + mode); },
          _stopSingular() {}, toUnhook: { dispose: () => runDelayer.dispose() } };
      }
      const invoke = owner => mode === 'cursor' ? makeCursor.call(owner)({}) : mode === 'focus' ? makeFocus.call(owner)({}) : restore.call(owner, 250);
      const before = unhandled.length;
      const owner = fixture(false);
      invoke(owner);
      if (mode === 'restore') invoke(owner);
      dispose.call(owner);
      await pause(20);
      const canceled = unhandled.slice(before);
      const realOwner = fixture(true);
      invoke(realOwner);
      await pause(80);
      dispose.call(realOwner);
      outcomes.push({ mode, canceled });
    }
    console.log(JSON.stringify({ outcomes, surfaced, unhandled }));
  `
}

describe('Monaco 0.55.1 cancellation backport', () => {
  const probes = new Map<'esm' | 'amd', { original: string; patched: string }>()
  // Parsing the multi-megabyte AMD distribution is setup CPU work. Give that
  // extraction a bounded 30s budget under the full parallel suite, keeping the
  // individual behavioral tests at Vitest's unchanged five-second timeout.
  beforeAll(() => {
    for (const format of ['esm', 'amd'] as const) {
      const relative = format === 'esm' ? esmPath : amdPath
      probes.set(format, {
        original: probeSource(format, originals.get(relative)!),
        patched: probeSource(format, patched.get(relative)!),
      })
    }
  }, 30_000)

  it('changes only the pinned three ignored promise results in both distributions', () => {
    expect(verifyMonacoCancellationBackport(patchedRoot)).toBe('0.55.1')
    for (const [relative, integrity] of Object.entries(MONACO_BACKPORT.files) as Array<[string, { original: string; patched: string }]>) {
      expect(sha256(originals.get(relative))).toBe(integrity.original)
      expect(sha256(patched.get(relative))).toBe(integrity.patched)
      const suffix = relative === esmPath ? '.catch(onUnexpectedError)' : '.catch(De)'
      expect(patched.get(relative)!.split(suffix).length - originals.get(relative)!.split(suffix).length).toBe(3)
    }
  })

  for (const format of ['esm', 'amd'] as const) it(`${format} consumes disposal/restore cancellation and surfaces genuine callback errors`, () => {
    const scripts = probes.get(format)!
    const probe = (script: string) => JSON.parse(execFileSync(process.execPath,
      ['--input-type=module', '-e', script], { encoding: 'utf8', timeout: 2_000 }))
    const red = probe(scripts.original)
    expect(red.outcomes.map((outcome: { canceled: unknown[] }) => outcome.canceled.length)).toEqual([1, 1, 2])
    expect(red.unhandled.map((error: { message: string }) => error.message)).toContain('genuine-cursor')
    const green = probe(scripts.patched)
    expect(green.outcomes.map((outcome: { canceled: unknown[] }) => outcome.canceled)).toEqual([[], [], []])
    expect(green.unhandled).toEqual([])
    expect(green.surfaced).toEqual(['genuine-cursor', 'genuine-focus', 'genuine-restore'])
  })

  it('rejects unsupported versions or unpatched/drifted vendor bytes', () => {
    const fixture = path.join(root, 'invalid')
    mkdirSync(fixture)
    writeFileSync(path.join(fixture, 'package.json'), JSON.stringify({ version: '0.55.2' }))
    expect(() => verifyMonacoCancellationBackport(fixture)).toThrow('Unsupported Monaco backport version')
    writeFileSync(path.join(fixture, 'package.json'), JSON.stringify({ version: '0.55.1' }))
    mkdirSync(path.dirname(path.join(fixture, esmPath)), { recursive: true })
    writeFileSync(path.join(fixture, esmPath), originals.get(esmPath)!)
    expect(() => verifyMonacoCancellationBackport(fixture)).toThrow('backport missing or changed')
  })
})

describe('Monaco generated asset identity', () => {
  it('replaces same-version legacy assets, reuses exact bytes, and repairs missing/corrupt output', async () => {
    const outputRoot = path.join(root, 'prepared')
    const outputAmd = path.join(outputRoot, 'vs', path.basename(amdPath))
    mkdirSync(path.dirname(outputAmd), { recursive: true })
    writeFileSync(outputAmd, originals.get(amdPath)!)
    writeFileSync(path.join(outputRoot, '.version'), '0.55.1\n')
    expect(await prepareMonaco({ monacoRoot: patchedRoot, outputRoot })).toBe(true)
    expect(sha256(readFileSync(outputAmd))).toBe(MONACO_BACKPORT.files[amdPath].patched)
    const marker = readFileSync(path.join(outputRoot, '.version'), 'utf8')
    expect(marker).toMatch(/^0\.55\.1:[a-f0-9]{64}\n$/)
    expect(await prepareMonaco({ monacoRoot: patchedRoot, outputRoot })).toBe(false)
    writeFileSync(outputAmd, originals.get(amdPath)!)
    expect(await prepareMonaco({ monacoRoot: patchedRoot, outputRoot })).toBe(true)
    rmSync(outputAmd)
    expect(await prepareMonaco({ monacoRoot: patchedRoot, outputRoot })).toBe(true)
  })

  it('invalidates same-version cache when another copied asset changes', async () => {
    const outputRoot = path.join(root, 'asset-change')
    expect(await prepareMonaco({ monacoRoot: patchedRoot, outputRoot })).toBe(true)
    const before = readFileSync(path.join(outputRoot, '.version'), 'utf8')
    writeFileSync(path.join(patchedRoot, 'min', 'vs', 'added.css'), 'new same-version asset')
    expect(await prepareMonaco({ monacoRoot: patchedRoot, outputRoot })).toBe(true)
    expect(readFileSync(path.join(outputRoot, '.version'), 'utf8')).not.toBe(before)
    expect(readFileSync(path.join(outputRoot, 'vs', 'added.css'), 'utf8')).toBe('new same-version asset')
  })

  it('fingerprints sorted relative paths and bytes, independent of creation order', async () => {
    const left = path.join(root, 'left'); const right = path.join(root, 'right')
    mkdirSync(left); mkdirSync(right)
    for (const name of ['b.js', 'a.js']) writeFileSync(path.join(left, name), name)
    for (const name of ['a.js', 'b.js']) writeFileSync(path.join(right, name), name)
    expect(await fingerprintMonacoAssets(left)).toBe(await fingerprintMonacoAssets(right))
    writeFileSync(path.join(right, 'a.js'), 'changed bytes')
    expect(await fingerprintMonacoAssets(left)).not.toBe(await fingerprintMonacoAssets(right))
  })
})
