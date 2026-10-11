import { createRequire } from 'node:module'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { runInNewContext } from 'node:vm'
import { Session } from 'node:inspector'
import { describe, expect, it } from 'vitest'
import {
  applyCursorBackport, CURSOR_HELPER, HOST_MARKUP, NEXT_VERSION,
  readVendoredRenderer, REACT_VERSION, RENDERER_BYTES, RENDERER_SHA256,
  replayProbeLocations, selectProbeBreakpoint, sha256, undoCursorBackport,
} from '../../e2e/helpers/hydration-host-replay'

const frontendRoot = process.cwd()

describe('Next-vendored host hydration replay diagnostic', () => {
  it('pins the actual Next renderer and leaves the baseline bytes unchanged', () => {
    const vendor = readVendoredRenderer(frontendRoot)
    expect(vendor.nextVersion).toBe(NEXT_VERSION)
    expect(Buffer.byteLength(vendor.source)).toBe(RENDERER_BYTES)
    expect(sha256(vendor.source)).toBe(RENDERER_SHA256)
    expect(vendor.source).toContain(`exports.version = "${REACT_VERSION}";`)
    expect(vendor.source).not.toContain('popHydrationStateOnInterruptedWork')
    expect(HOST_MARKUP).toContain('<div id="target"><section id="child">lazy child</section></div>')
  })

  it('reverses only the faithful upstream helper and case-5 call', () => {
    const { source } = readVendoredRenderer(frontendRoot)
    const patched = applyCursorBackport(source)
    expect(patched).not.toBe(source)
    expect(patched).toContain(CURSOR_HELPER)
    expect(patched).toContain('case 5:\n      resetHooksOnUnwind(next);\n      popHydrationStateOnInterruptedWork(next);\n    default:')
    expect(undoCursorBackport(patched)).toBe(source)
    expect(() => applyCursorBackport(source + '\n')).toThrow('renderer changed')
    expect(() => applyCursorBackport(patched)).toThrow('renderer changed')
    expect(() => undoCursorBackport(patched.replace('    nextHydratableInstance = fiber.stateNode;', '    nextHydratableInstance = null;'))).toThrow('one exact')
    expect(() => undoCursorBackport(patched + CURSOR_HELPER + 'function upgradeHydrationErrorsToRecoverable() {')).toThrow('one exact')
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
      const patchedPath = path.join(temporaryDirectory, 'patched.cjs')
      writeFileSync(patchedPath, applyCursorBackport(vendor.source))
      for (const rendererPath of [vendor.rendererPath, patchedPath]) {
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
      expect(sha256(readFileSync(vendor.rendererPath))).toBe(RENDERER_SHA256)
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
