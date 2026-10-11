import { createRequire } from 'node:module'
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'

import { expect, test, type Browser, type CDPSession } from '@playwright/test'
import {
  HOST_IDS, HOST_MARKUP, NEXT_VERSION, ORIGINAL_CHUNK,
  readVendoredRenderer, REACT_VERSION, RENDERER_BYTES, RENDERER_SHA256,
  PATCHED_RENDERER_BYTES, PATCHED_RENDERER_SHA256,
  REPLAY_ISSUE, replayProbeLocations, selectProbeBreakpoint, sha256, UPSTREAM_CURSOR_FIX,
} from './helpers/hydration-host-replay'

type Variant = 'baseline' | 'patched'
type ChildState = 'prefilled' | 'pending'
type Probe = {
  event: string; tag: number; hostId: string | null; isHydrating: boolean
  parentMatches: boolean; cursorId: string | null; status?: string; suspendedReason?: number
}
type Observation = {
  variant: Variant; childState: ChildState; initialMarkup: string; finalMarkup: string
  identities: Record<string, boolean>; events: string[]; probes: Probe[]
  recoverableErrors: Array<{ message: string; stack: string }>
  uncaughtErrors: string[]; caughtErrors: string[]; committed: boolean
  reactVersion: string; rendererVersion: string
  pageErrors: string[]; consoleErrors: string[]; unexpectedRequests: string[]
  debuggerPauses: number; disposed?: boolean
  bundleSha256: string
  debuggerBindings: Array<{ requested: { lineNumber: number; columnNumber: number }; actual: { lineNumber: number; columnNumber: number } }>
}

const matrix: Array<{ variant: Variant; childState: ChildState }> = [
  { variant: 'baseline', childState: 'prefilled' },
  { variant: 'patched', childState: 'prefilled' },
  { variant: 'baseline', childState: 'pending' },
  { variant: 'patched', childState: 'pending' },
]
const frontendRoot = path.resolve(process.cwd())

function browserSource(rendererPath: string) {
  return `
import React from 'next/dist/compiled/react'
import { hydrateRoot, version as rendererVersion } from ${JSON.stringify(rendererPath)}

globalThis.__hostReplayProbes = []
let root
let state
let initialNodes

globalThis.startHostReplay = (childState) => {
  if (root || state) throw new Error('Hydration fixture can only run once per page')
  const container = document.getElementById('root')
  initialNodes = Object.fromEntries(${JSON.stringify(HOST_IDS)}.map(id => [id, document.getElementById(id)]))
  state = {
    initialMarkup: container.innerHTML, events: [], recoverableErrors: [],
    uncaughtErrors: [], caughtErrors: [], committed: false,
    reactVersion: React.version, rendererVersion,
  }
  const chunk = {
    status: 'pending', value: null, listeners: [],
    then(resolve) {
      if (this.status === 'fulfilled') resolve(this.value)
      else this.listeners.push(resolve)
    },
  }
  const fulfill = () => {
    if (chunk.status !== 'pending') throw new Error('Synthetic chunk resolved twice')
    state.events.push('chunk-fulfilled')
    chunk.status = 'fulfilled'
    chunk.value = { default: React.createElement('section', { id: 'child' }, 'lazy child') }
    const listeners = chunk.listeners.splice(0)
    listeners.forEach(listener => listener(chunk.value))
  }
  if (childState === 'prefilled') fulfill()
  const lazyNode = React.lazy(() => {
    state.events.push('lazy-initializer')
    // React's real concurrent work loop yields after SuspendedOnImmediate.
    // The microtask runs before Scheduler's next host task. No clock sleeps,
    // custom Scheduler, repeated timing attempts, or downloaded repro code.
    if (childState === 'pending') queueMicrotask(fulfill)
    return chunk
  })
  function Before() {
    state.events.push('before')
    return React.createElement('p', { id: 'before' }, 'before')
  }
  function After() {
    state.events.push('after')
    return React.createElement('p', { id: 'after' }, 'after')
  }
  function App() {
    React.useLayoutEffect(() => {
      state.events.push('committed')
      state.committed = true
    }, [])
    return React.createElement('div', { id: 'outer' },
      React.createElement(Before),
      // A bare lazy NODE, like a Flight $L child, suspends the host fiber.
      React.createElement('div', { id: 'target' }, lazyNode),
      React.createElement(After))
  }
  state.events.push('hydration-start')
  React.startTransition(() => {
    root = hydrateRoot(container, React.createElement(App), {
      onRecoverableError(error) {
        state.recoverableErrors.push({ message: error.message, stack: error.stack || '' })
      },
      onUncaughtError(error) { state.uncaughtErrors.push(error.message) },
      onCaughtError(error) { state.caughtErrors.push(error.message) },
    })
  })
}
globalThis.readHostReplay = () => ({
  ...state, finalMarkup: document.getElementById('root').innerHTML,
  probes: globalThis.__hostReplayProbes,
  identities: Object.fromEntries(${JSON.stringify(HOST_IDS)}.map(id => [id, document.getElementById(id) === initialNodes[id]])),
})
globalThis.disposeHostReplay = () => {
  root.unmount()
  return document.getElementById('root').childNodes.length === 0
}
`
}

async function boundedCleanup(action: () => Promise<unknown>, label: string) {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([
      action(),
      new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} cleanup exceeded 5s`)), 5_000) }),
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

async function runArm(browser: Browser, origin: string, variant: Variant, childState: ChildState, bundle: string) {
  const context = await browser.newContext({ serviceWorkers: 'block' })
  let cdp: CDPSession | undefined
  const pageErrors: string[] = []
  const consoleErrors: string[] = []
  const unexpectedRequests: string[] = []
  const debuggerBindings: Observation['debuggerBindings'] = []
  let debuggerPauses = 0
  try {
    await context.route('**/*', async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.origin === origin && request.method() === 'GET' && ['/', `/${variant}.js`, '/favicon.ico'].includes(url.pathname)) {
        await route.continue()
      } else {
        unexpectedRequests.push(`${request.method()} ${url.origin}${url.pathname}`)
        await route.abort()
      }
    })
    const page = await context.newPage()
    page.setDefaultTimeout(10_000)
    page.setDefaultNavigationTimeout(10_000)
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()) })
    await page.routeWebSocket('**/*', (socket) => { unexpectedRequests.push('WebSocket'); socket.close() })
    await page.goto(`${origin}/?variant=${variant}`, { waitUntil: 'load' })
    expect(await page.locator('#root').innerHTML()).toBe(HOST_MARKUP)

    cdp = await context.newCDPSession(page)
    const scriptIds: string[] = []
    cdp.on('Debugger.scriptParsed', (event) => { if (event.url === `${origin}/${variant}.js`) scriptIds.push(event.scriptId) })
    cdp.on('Debugger.paused', () => {
      debuggerPauses += 1
      // An unexpected pause fails the arm; resume only to let bounded cleanup finish.
      void cdp?.send('Debugger.resume').catch(() => undefined)
    })
    await cdp.send('Debugger.enable')
    expect(scriptIds).toHaveLength(1)
    const scriptId = scriptIds[0]
    const { scriptSource } = await cdp.send('Debugger.getScriptSource', { scriptId })
    expect(sha256(scriptSource)).toBe(sha256(bundle))
    const locations = replayProbeLocations(bundle)
    const probes = [
      {
        location: locations.resolvedThenable,
        condition: `(globalThis.__hostReplayProbes.push({event:'resolved-thenable',tag:lanes.tag,hostId:lanes.stateNode && lanes.stateNode.id,isHydrating:isHydrating,parentMatches:hydrationParentFiber === lanes,cursorId:nextHydratableInstance && nextHydratableInstance.id,status:thrownValue.status,suspendedReason:workInProgressSuspendedReason}), false)`,
      },
      {
        location: locations.replay,
        condition: `(globalThis.__hostReplayProbes.push({event:'host-replay',tag:unitOfWork.tag,hostId:unitOfWork.stateNode && unitOfWork.stateNode.id,isHydrating:isHydrating,parentMatches:hydrationParentFiber === unitOfWork,cursorId:nextHydratableInstance && nextHydratableInstance.id}), false)`,
      },
    ]
    for (const probe of probes) {
      // V8's executable breakpoint can be on the RHS of the first `var`
      // statement, rather than its first character. Select the first actual
      // breakable position within this already-verified statement's line.
      const { locations: possibleLocations } = await cdp.send('Debugger.getPossibleBreakpoints', {
        start: { scriptId, ...probe.location },
        end: { scriptId, lineNumber: probe.location.lineNumber + 1, columnNumber: 0 },
        restrictToFunction: true,
      })
      const exactLocation = selectProbeBreakpoint(probe.location, possibleLocations, scriptId)
      const binding = await cdp.send('Debugger.setBreakpoint', { location: exactLocation, condition: probe.condition })
      expect(binding.breakpointId).toBeTruthy()
      expect(binding.actualLocation).toEqual(exactLocation)
      debuggerBindings.push({ requested: probe.location, actual: { lineNumber: exactLocation.lineNumber, columnNumber: exactLocation.columnNumber } })
    }

    await page.evaluate((mode) => (globalThis as unknown as { startHostReplay: (mode: string) => void }).startHostReplay(mode), childState)
    await page.waitForFunction(() => (globalThis as unknown as { readHostReplay: () => Observation }).readHostReplay().committed)
    // Drain a microtask and one host task after commit so recoverable callbacks
    // and error listeners cannot race the assertions.
    await page.evaluate(() => new Promise<void>((resolve) => setTimeout(resolve, 0)))
    const observation = await page.evaluate(() => (globalThis as unknown as { readHostReplay: () => Observation }).readHostReplay())
    const disposed = await page.evaluate(() => (globalThis as unknown as { disposeHostReplay: () => boolean }).disposeHostReplay())
    return { ...observation, variant, childState, pageErrors, consoleErrors, unexpectedRequests, debuggerPauses, disposed, bundleSha256: sha256(bundle), debuggerBindings }
  } finally {
    try {
      if (cdp) await boundedCleanup(() => cdp!.detach(), 'CDP')
    } finally {
      await boundedCleanup(() => context.close(), 'Browser context')
    }
  }
}

test('pinned Next host replay reproduces #418 and the upstream cursor backport preserves SSR nodes', async ({ browser, browserName }, testInfo) => {
  test.setTimeout(90_000)
  expect(browserName).toBe('chromium')
  const vendor = readVendoredRenderer(frontendRoot)
  const temporaryDirectory = mkdtempSync(path.join(os.tmpdir(), 'latexy-host-replay-'))
  let server: http.Server | undefined
  const observations: Observation[] = []
  const serverRequests: string[] = []
  const evidence = {
    nextVersion: NEXT_VERSION, reactVersion: REACT_VERSION,
    baselineRenderer: { bytes: RENDERER_BYTES, sha256: RENDERER_SHA256, origin: 'exact inverse of installed patched runtime' },
    patchedRenderer: { bytes: PATCHED_RENDERER_BYTES, sha256: PATCHED_RENDERER_SHA256, origin: 'effective installed runtime' },
    originalCiChunk: ORIGINAL_CHUNK, sources: [UPSTREAM_CURSOR_FIX, REPLAY_ISSUE],
    instrumentation: 'Identical Chromium CDP conditional logpoints return false and only record state. Debugger attachment may affect scheduling. Baseline is the exact inverse of the installed patch; patched arm imports the effective installed renderer. Matched vendored Scheduler is unchanged. Pending status thenable resolves in a microtask; no timing rerolls.',
    expectedMatrix: matrix, observations, serverRequests,
  }
  try {
    const vitestPackage = createRequire(path.join(frontendRoot, 'package.json')).resolve('vitest/package.json')
    const esbuildEntry = createRequire(vitestPackage).resolve('esbuild')
    const { build } = await import(esbuildEntry)
    const originalRendererPath = path.join(temporaryDirectory, 'react-dom-client.original.cjs')
    writeFileSync(originalRendererPath, vendor.originalSource)
    const bundles: Record<Variant, string> = { baseline: '', patched: '' }
    for (const variant of ['baseline', 'patched'] as const) {
      const entryPath = path.join(temporaryDirectory, `${variant}.tsx`)
      writeFileSync(entryPath, browserSource(variant === 'baseline' ? originalRendererPath : vendor.rendererPath))
      const result = await build({
        absWorkingDir: frontendRoot, entryPoints: [entryPath], bundle: true,
        format: 'iife', platform: 'browser', write: false, metafile: true,
        nodePaths: [realpathSync(path.join(frontendRoot, 'node_modules'))],
        alias: vendor.alias, define: { 'process.env.NODE_ENV': '"production"' },
      })
      expect(result.outputFiles).toHaveLength(1)
      bundles[variant] = result.outputFiles[0].text
      replayProbeLocations(bundles[variant])
      const inputs = Object.keys(result.metafile!.inputs).map((input) => path.resolve(frontendRoot, input))
      for (const dependency of Object.values(vendor.alias)) expect(inputs).toContain(dependency)
      expect(inputs).toContain(variant === 'baseline' ? originalRendererPath : vendor.rendererPath)
      expect(inputs.some((input) => /\/react(?:-dom)?@18\./.test(input))).toBe(false)
    }
    server = http.createServer((request, response) => {
      const url = new URL(request.url ?? '/', 'http://127.0.0.1')
      if (request.method === 'GET' && (url.pathname === '/baseline.js' || url.pathname === '/patched.js')) {
        response.writeHead(200, { 'content-type': 'application/javascript', 'cache-control': 'no-store' })
        response.end(bundles[url.pathname === '/baseline.js' ? 'baseline' : 'patched'])
      } else if (request.method === 'GET' && url.pathname === '/') {
        const variant = url.searchParams.get('variant')
        if (variant !== 'baseline' && variant !== 'patched') { response.writeHead(400); response.end(); return }
        response.writeHead(200, { 'content-type': 'text/html', 'cache-control': 'no-store' })
        response.end(`<!doctype html><html><head><link rel="icon" href="data:,"></head><body><div id="root">${HOST_MARKUP}</div><script src="/${variant}.js"></script></body></html>`)
      } else if (request.method === 'GET' && url.pathname === '/favicon.ico') {
        response.writeHead(204); response.end()
      } else {
        serverRequests.push(`${request.method} ${url.pathname}`)
        response.writeHead(404); response.end()
      }
    })
    await new Promise<void>((resolve, reject) => {
      server!.once('error', reject)
      server!.listen(0, '127.0.0.1', resolve)
    })
    const address = server.address()
    if (!address || typeof address === 'string') throw new Error('Synthetic host replay server did not bind')
    const origin = `http://127.0.0.1:${address.port}`
    for (const arm of matrix) {
      const result = await runArm(browser, origin, arm.variant, arm.childState, bundles[arm.variant])
      observations.push(result)
      expect(result.initialMarkup).toBe(HOST_MARKUP)
      expect(result.finalMarkup).toBe(HOST_MARKUP)
      expect(result.reactVersion).toBe(REACT_VERSION)
      expect(result.rendererVersion).toBe(REACT_VERSION)
      expect(result.committed).toBe(true)
      expect(result.disposed).toBe(true)
      expect(result.pageErrors).toEqual([])
      expect(result.consoleErrors).toEqual([])
      expect(result.uncaughtErrors).toEqual([])
      expect(result.caughtErrors).toEqual([])
      expect(result.unexpectedRequests).toEqual([])
      expect(result.debuggerPauses).toBe(0)
      expect(result.debuggerBindings).toHaveLength(2)
      expect(result.events.filter((event) => event === 'lazy-initializer')).toHaveLength(1)
      expect(result.events.filter((event) => event === 'chunk-fulfilled')).toHaveLength(1)
      expect(result.events.filter((event) => event === 'after')).toHaveLength(1)
      expect(result.events.filter((event) => event === 'committed')).toHaveLength(1)
      const red = arm.variant === 'baseline' && arm.childState === 'pending'
      expect(result.events.filter((event) => event === 'before')).toHaveLength(red ? 2 : 1)
      expect(result.identities).toEqual(Object.fromEntries(HOST_IDS.map((id) => [id, !red])))
      if (arm.childState === 'pending') {
        expect(result.events.indexOf('hydration-start')).toBeLessThan(result.events.indexOf('lazy-initializer'))
        expect(result.events.indexOf('lazy-initializer')).toBeLessThan(result.events.indexOf('chunk-fulfilled'))
        expect(result.probes).toEqual([
          { event: 'resolved-thenable', tag: 5, hostId: 'target', isHydrating: true, parentMatches: true, cursorId: 'child', status: 'fulfilled', suspendedReason: 7 },
          { event: 'host-replay', tag: 5, hostId: 'target', isHydrating: true, parentMatches: true, cursorId: 'child' },
        ])
      } else {
        expect(result.events.indexOf('chunk-fulfilled')).toBeLessThan(result.events.indexOf('hydration-start'))
        expect(result.probes).toEqual([])
      }
      if (red) {
        expect(result.recoverableErrors).toHaveLength(1)
        expect(result.recoverableErrors[0].message).toMatch(/^Minified React error #418;/)
        expect(result.recoverableErrors[0].stack).toContain('replaySuspendedUnitOfWork')
      } else {
        expect(result.recoverableErrors).toEqual([])
      }
    }
    expect(observations.map(({ variant, childState }) => ({ variant, childState }))).toEqual(matrix)
    expect(observations).toHaveLength(4)
    expect(new Set(observations.map((row) => row.initialMarkup)).size).toBe(1)
    expect(observations[2].probes).toEqual(observations[3].probes)
    expect(serverRequests).toEqual([])
    // Ensure building/running the diagnostic never changed the installed bytes.
    expect(sha256(readFileSync(vendor.rendererPath))).toBe(PATCHED_RENDERER_SHA256)
  } finally {
    try {
      await testInfo.attach('next-vendored-host-replay.json', { body: Buffer.from(JSON.stringify(evidence, null, 2)), contentType: 'application/json' })
    } finally {
      try {
        if (server?.listening) await boundedCleanup(() => new Promise<void>((resolve, reject) => {
          server!.close((error) => error ? reject(error) : resolve())
          server!.closeAllConnections()
        }), 'Loopback server')
      } finally {
        rmSync(temporaryDirectory, { recursive: true, force: true })
      }
    }
  }
})
