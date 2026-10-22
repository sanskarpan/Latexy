import { createRequire } from 'node:module'
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { runInNewContext } from 'node:vm'
import { Session } from 'node:inspector'
import { describe, expect, it } from 'vitest'
import {
  applyCursorBackport, CURSOR_HELPER, HOST_MARKUP, NEXT_VERSION,
  readVendoredRenderer, REACT_VERSION, RENDERER_BYTES, RENDERER_SHA256,
  replayProbeLocations, selectProbeBreakpoint, sha256, undoCursorBackport,
  PATCHED_RENDERER_BYTES, PATCHED_RENDERER_SHA256, INTEGRITY, assertRendererSource,
  verifyNextHydrationBackport,
} from '../../e2e/helpers/hydration-host-replay'

const frontendRoot = process.cwd()

describe('Next-vendored host hydration replay diagnostic', () => {
  it('pins the effective installed patched renderer and reconstructs the exact original', () => {
    const vendor = readVendoredRenderer(frontendRoot)
    expect(vendor.nextVersion).toBe(NEXT_VERSION)
    expect(Buffer.byteLength(vendor.source)).toBe(PATCHED_RENDERER_BYTES)
    expect(sha256(vendor.source)).toBe(PATCHED_RENDERER_SHA256)
    expect(vendor.source).toContain(`exports.version = "${REACT_VERSION}";`)
    expect(vendor.source).toContain(CURSOR_HELPER)
    expect(Buffer.byteLength(vendor.originalSource)).toBe(RENDERER_BYTES)
    expect(sha256(vendor.originalSource)).toBe(RENDERER_SHA256)
    expect(vendor.originalSource).not.toContain('popHydrationStateOnInterruptedWork')
    expect(HOST_MARKUP).toContain('<div id="target"><section id="child">lazy child</section></div>')
  })

  it('reverses only the faithful upstream helper and case-5 call', () => {
    const { originalSource: source, source: installed } = readVendoredRenderer(frontendRoot)
    const patched = applyCursorBackport(source)
    expect(patched).toBe(installed)
    expect(patched).not.toBe(source)
    expect(patched).toContain(CURSOR_HELPER)
    expect(patched).toContain('case 5:\n      resetHooksOnUnwind(next);\n      popHydrationStateOnInterruptedWork(next);\n    default:')
    expect(undoCursorBackport(patched)).toBe(source)
    expect(() => applyCursorBackport(source + '\n')).toThrow('renderer changed')
    expect(() => applyCursorBackport(patched)).toThrow('renderer changed')
    expect(() => undoCursorBackport(patched.replace('    nextHydratableInstance = fiber.stateNode;', '    nextHydratableInstance = null;'))).toThrow('renderer changed')
    expect(() => undoCursorBackport(patched + CURSOR_HELPER + 'function upgradeHydrationErrorsToRecoverable() {')).toThrow('renderer changed')
  })

  it('validates all four normal renderer postimages and their exact inverse preimages', () => {
    const { nextRoot } = verifyNextHydrationBackport(frontendRoot)
    for (const [filename, images] of Object.entries(INTEGRITY.renderers) as Array<[string, { original: { bytes: number; sha256: string }; patched: { bytes: number; sha256: string } }]>) {
      const source = readFileSync(path.join(nextRoot, 'dist/compiled/react-dom/cjs', filename), 'utf8')
      assertRendererSource(source, filename, 'patched')
      expect(sha256(source)).toBe(images.patched.sha256)
      const original = undoCursorBackport(source, filename)
      expect(sha256(original)).toBe(images.original.sha256)
      expect(applyCursorBackport(original, filename)).toBe(source)
      expect(() => assertRendererSource(original, filename, 'patched')).toThrow('renderer changed')
      expect(() => assertRendererSource(source + '\n', filename, 'patched')).toThrow('renderer changed')
      const fiber = filename.endsWith('.development.js') ? 'unitOfWork' : 'next'
      expect(source).toContain(`resetHooksOnUnwind(${fiber});\n${filename.endsWith('.development.js') ? '    ' : ''}      popHydrationStateOnInterruptedWork(${fiber});\n${filename.endsWith('.development.js') ? '    ' : ''}    default:`)
    }
    expect(() => assertRendererSource('', 'react-dom-experimental.production.js')).toThrow('channel')
    for (const field of ['ppr', 'taint', 'viewTransition', 'routerBFCache']) {
      expect(() => verifyNextHydrationBackport(frontendRoot, { experimental: { [field]: true } })).toThrow('experimental React channel')
    }
  })

  it('rejects every nonempty inherited experimental server-channel selector', () => {
    const previous = process.env.__NEXT_EXPERIMENTAL_REACT
    try {
      for (const value of ['0', 'false', 'true']) {
        process.env.__NEXT_EXPERIMENTAL_REACT = value
        expect(() => verifyNextHydrationBackport(frontendRoot)).toThrow('experimental React channel')
      }
      process.env.__NEXT_EXPERIMENTAL_REACT = ''
      expect(() => verifyNextHydrationBackport(frontendRoot)).not.toThrow()
      delete process.env.__NEXT_EXPERIMENTAL_REACT
      expect(() => verifyNextHydrationBackport(frontendRoot)).not.toThrow()
    } finally {
      if (previous === undefined) delete process.env.__NEXT_EXPERIMENTAL_REACT
      else process.env.__NEXT_EXPERIMENTAL_REACT = previous
    }
  })

  it('fails closed for missing patches, modified companions, wrong versions and missing files', () => {
    const { nextRoot } = verifyNextHydrationBackport(frontendRoot)
    const temporaryDirectory = mkdtempSync(path.join(os.tmpdir(), 'latexy-replay-integrity-unit-'))
    const isolatedNext = path.join(temporaryDirectory, 'node_modules/next')
    try {
      mkdirSync(path.join(isolatedNext, 'dist/lib'), { recursive: true })
      writeFileSync(path.join(temporaryDirectory, 'package.json'), '{}')
      cpSync(path.join(nextRoot, 'package.json'), path.join(isolatedNext, 'package.json'))
      cpSync(path.join(nextRoot, 'dist/lib/needs-experimental-react.js'), path.join(isolatedNext, 'dist/lib/needs-experimental-react.js'))
      for (const name of Object.keys(INTEGRITY.companions)) {
        cpSync(path.join(nextRoot, 'dist/compiled', name), path.join(isolatedNext, 'dist/compiled', name), { recursive: true })
      }
      expect(() => verifyNextHydrationBackport(temporaryDirectory)).not.toThrow()
      const renderer = path.join(isolatedNext, 'dist/compiled/react-dom/cjs/react-dom-client.production.js')
      const patched = readFileSync(renderer, 'utf8')
      writeFileSync(renderer, undoCursorBackport(patched))
      expect(() => verifyNextHydrationBackport(temporaryDirectory)).toThrow('renderer changed')
      writeFileSync(renderer, patched + '\n')
      expect(() => verifyNextHydrationBackport(temporaryDirectory)).toThrow('renderer changed')
      writeFileSync(renderer, patched)
      for (const name of Object.keys(INTEGRITY.companions)) {
        const license = path.join(isolatedNext, 'dist/compiled', name, 'LICENSE')
        const original = readFileSync(license, 'utf8')
        writeFileSync(license, original + '\n')
        expect(() => verifyNextHydrationBackport(temporaryDirectory)).toThrow(`matched companion changed: ${name}`)
        writeFileSync(license, original)
      }
      const packagePath = path.join(isolatedNext, 'package.json')
      const metadata = JSON.parse(readFileSync(packagePath, 'utf8'))
      writeFileSync(packagePath, JSON.stringify({ ...metadata, version: '15.5.29' }))
      expect(() => verifyNextHydrationBackport(temporaryDirectory)).toThrow('Expected exact Next 15.5.28')
      writeFileSync(packagePath, JSON.stringify(metadata))
      rmSync(renderer)
      expect(() => verifyNextHydrationBackport(temporaryDirectory)).toThrow()
      expect(sha256(readFileSync(path.join(nextRoot, 'dist/compiled/react-dom/cjs/react-dom-client.production.js')))).toBe(PATCHED_RENDERER_SHA256)
    } finally {
      rmSync(temporaryDirectory, { recursive: true, force: true })
    }
  })

  it('preserves upstream validity, insertion and host-only rewind branches', () => {
    const node = { id: 'target' }
    const cursor = { id: 'child' }
    const parent = { tag: 3 }
    for (const [tag, isHydrating, parentMatches, stateNode, shouldPop, shouldRewind] of [
      [5, true, false, node, false, false],
      [5, false, true, node, true, false],
      [5, true, true, node, true, true],
      [5, true, true, null, true, false],
      [27, true, true, node, true, false],
      [26, true, true, node, true, false],
    ] as const) {
      const fiber = { tag, stateNode, return: parent }
      const state = {
        fiber, hydrationParentFiber: parentMatches ? fiber : parent,
        isHydrating, nextHydratableInstance: cursor as { id: string } | null,
        popCount: 0,
      }
      const context = {
        ...state,
        popToNextHostParent: () => {
          context.popCount += 1
          context.hydrationParentFiber = parent
        },
      }
      runInNewContext(`${CURSOR_HELPER}\npopHydrationStateOnInterruptedWork(fiber);`, context)
      expect(context.popCount).toBe(shouldPop ? 1 : 0)
      expect(context.isHydrating).toBe(true)
      expect(context.nextHydratableInstance).toBe(shouldRewind ? node : cursor)
      expect(context.hydrationParentFiber).toBe(parent)
    }
  })

  it('builds both real vendor variants and binds identical observational probe sites without a browser', async () => {
    const vendor = readVendoredRenderer(frontendRoot)
    const temporaryDirectory = mkdtempSync(path.join(os.tmpdir(), 'latexy-replay-transform-unit-'))
    try {
      const vitestPackage = createRequire(path.join(frontendRoot, 'package.json')).resolve('vitest/package.json')
      const { build } = await import(createRequire(vitestPackage).resolve('esbuild'))
      const originalPath = path.join(temporaryDirectory, 'original.cjs')
      writeFileSync(originalPath, vendor.originalSource)
      for (const rendererPath of [originalPath, vendor.rendererPath]) {
        const entryPath = path.join(temporaryDirectory, 'entry.js')
        writeFileSync(entryPath, `import React from 'next/dist/compiled/react'; import { hydrateRoot } from ${JSON.stringify(rendererPath)}; window.fixture = { React, hydrateRoot };`)
        const result = await build({
          absWorkingDir: frontendRoot, entryPoints: [entryPath], bundle: true,
          platform: 'browser', format: 'iife', write: false, metafile: true,
          alias: vendor.alias, define: { 'process.env.NODE_ENV': '"production"' },
        })
        expect(result.outputFiles).toHaveLength(1)
        const bundle = result.outputFiles[0].text
        const locations = replayProbeLocations(bundle)
        const lines = bundle.split('\n')
        expect(lines[locations.replay.lineNumber].slice(locations.replay.columnNumber)).toMatch(/^var next = unitOfWork;/)
        expect(lines[locations.resolvedThenable.lineNumber].slice(locations.resolvedThenable.columnNumber)).toMatch(/^isThenableResolved\(thrownValue\)/)
        const inputs = Object.keys(result.metafile!.inputs).map((input) => path.resolve(frontendRoot, input))
        for (const dependency of Object.values(vendor.alias)) expect(inputs).toContain(dependency)
        expect(inputs).toContain(rendererPath)
      }
      expect(sha256(readFileSync(vendor.rendererPath))).toBe(PATCHED_RENDERER_SHA256)
      expect(() => replayProbeLocations('')).toThrow('one exact')
    } finally {
      rmSync(temporaryDirectory, { recursive: true, force: true })
    }
  })

  it('selects the actual V8 same-statement breakpoint rather than the var keyword', async () => {
    // Only our small synthetic function is compiled here. The vendored renderer
    // and all DOM hydration run exclusively in the authorized Chromium CI test.
    const session = new Session()
    const command = <Result>(method: string, params: Record<string, unknown> = {}) => new Promise<Result>((resolve, reject) => {
      session.post(method, params, (error, result) => error ? reject(error) : resolve(result as Result))
    })
    session.connect()
    try {
      await command('Runtime.enable')
      await command('Debugger.enable')
      const { scriptId } = await command<{ scriptId: string }>('Runtime.compileScript', {
        expression: 'function replaySuspendedUnitOfWork(unitOfWork) {\n  var next = unitOfWork;\n  return next;\n}',
        sourceURL: `latexy-hydration-breakpoint-fixture-${process.pid}.js`, persistScript: true,
      })
      expect(scriptId).toBeTruthy()
      const requested = { lineNumber: 1, columnNumber: 2 }
      const { locations } = await command<{ locations: Array<{ scriptId: string; lineNumber: number; columnNumber: number }> }>('Debugger.getPossibleBreakpoints', {
        start: { scriptId, ...requested }, end: { scriptId, lineNumber: 2, columnNumber: 0 }, restrictToFunction: true,
      })
      const selected = selectProbeBreakpoint(requested, locations, scriptId)
      expect(selected.lineNumber).toBe(1)
      expect(selected.columnNumber).toBeGreaterThan(requested.columnNumber)
      const { actualLocation } = await command<{ actualLocation: typeof selected }>('Debugger.setBreakpoint', {
        location: selected, condition: 'false',
      })
      expect(actualLocation).toEqual(selected)
      expect(() => selectProbeBreakpoint(requested, [], scriptId)).toThrow('No executable')
      expect(() => selectProbeBreakpoint(requested, [{ scriptId, lineNumber: 2, columnNumber: 2 }], scriptId)).toThrow('No executable')
      expect(() => selectProbeBreakpoint(requested, [{ scriptId: 'other', lineNumber: 1, columnNumber: 13 }], scriptId)).toThrow('No executable')
    } finally {
      session.disconnect()
    }
  })
})
