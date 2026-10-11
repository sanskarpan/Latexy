import { readFileSync } from 'node:fs'
import { EventEmitter } from 'node:events'
import { createHash } from 'node:crypto'
import type { Page, Response, TestInfo } from '@playwright/test'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installLegacySettingsHydrationDiagnostics, LEGACY_SETTINGS_REACT_BYTES, LEGACY_SETTINGS_REACT_CHUNK, LEGACY_SETTINGS_REACT_SHA256 } from '../../e2e/helpers/legacy-settings-hydration-diagnostics'

import { mainDocumentKind, runOwnerIsolationHydrationFixture } from '../../e2e/helpers/owner-isolation-hydration-fixture'

vi.mock('node:crypto', () => ({ createHash: vi.fn() }))
const BASE = new URL('http://127.0.0.1:5184')
const OWN = 'owned-breakpoint'
const source = ' '.repeat(173133)
const validCapture = () => ({
  expected: { type: 'main', idCategory: 'main-content' },
  candidate: { nodeType: 8, nodeName: '#comment', idCategory: 'none', boundaryCommentKind: 'suspense-pending' },
  parent: { nodeType: 1, nodeName: 'main', idCategory: 'main-content', boundaryCommentKind: null },
  next: { nodeType: 1, nodeName: 'div', idCategory: 'none', boundaryCommentKind: null },
  parentFiberTag: 'main', hydrationParentIsExpected: true, alternatePresent: false,
  fibers: [{ tag: 5, type: 'main' }, { tag: 0, type: 'function' }],
})
type Handler = (params: Record<string, unknown>) => Promise<unknown>
class FakeCDP extends EventEmitter {
  handlers = new Map<string, Handler>()
  send = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    const handler = this.handlers.get(method)
    if (handler) return handler(params)
    if (method === 'Page.getFrameTree') return { frameTree: { frame: { id: 'main-frame' } } }
    if (method === 'Debugger.setBreakpointByUrl') return { breakpointId: OWN, locations: [] }
    if (method === 'Debugger.getScriptSource') return { scriptSource: source }
    if (method === 'Debugger.evaluateOnCallFrame') return { result: { type: 'object', value: validCapture() } }
    return {}
  })
  detach = vi.fn(async () => {})
}
function fake() {
  const cdp = new FakeCDP()
  const connect = vi.fn(async () => cdp)
  const close = vi.fn(async () => {})
  const frame = {}
  const page = Object.assign(new EventEmitter(), { context: () => ({ newCDPSession: connect }), close, mainFrame: () => frame }) as unknown as Page
  const attachments: string[] = []
  const attach = vi.fn(async (_name: string, options: { body: Buffer }) => { attachments.push(options.body.toString()) })
  const info = { attach, status: 'passed' } as unknown as TestInfo
  return { cdp, page, connect, close, info, attach, attachments }
}
function parsed(cdp: FakeCDP, scriptId = 'script-1', url = new URL(LEGACY_SETTINGS_REACT_CHUNK, BASE).href) {
  cdp.emit('Debugger.scriptParsed', { scriptId, url, executionContextId: scriptId === 'script-2' ? 2 : 1, executionContextAuxData: { frameId: 'main-frame', isDefault: true } })
  cdp.emit('Debugger.breakpointResolved', { breakpointId: OWN, location: { scriptId, lineNumber: 0, columnNumber: 35060 } })
}
function pause(cdp: FakeCDP, overrides: Record<string, unknown> = {}) {
  cdp.emit('Debugger.paused', {
    callFrames: [{ functionName: 'rD', callFrameId: 'frame', location: { scriptId: 'script-1', lineNumber: 0, columnNumber: 35060 } }],
    hitBreakpoints: [OWN], reason: 'other', ...overrides,
  })
}
async function flush() { for (let index = 0; index < 40; index++) await Promise.resolve() }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
function htmlResponse(page: Page, url = new URL('/workspace', BASE).href, overrides: { status?: number; contentType?: string; navigation?: boolean; resourceType?: string; frame?: unknown } = {}): Response {
  return {
    request: () => ({ isNavigationRequest: () => overrides.navigation ?? true, resourceType: () => overrides.resourceType ?? 'document', frame: () => overrides.frame ?? page.mainFrame() }),
    url: () => url, status: () => overrides.status ?? 200,
    headers: () => ({ 'content-type': overrides.contentType ?? 'text/html; charset=utf-8' }),
  } as unknown as Response
}
function respond(page: Page, response: Response) { (page as unknown as EventEmitter).emit('response', response) }
function report(test: ReturnType<typeof fake>) { return JSON.parse(test.attachments[0]) as { captures: unknown[]; failures: string[]; verified_scripts: number; resolved_scripts: number; capture_attempts: number; verified_documents: number; expected_main_documents: number; successful_main_app_documents: number; observation_status: string; scope: string } }

describe('original-case CDP Settings hydration diagnostic', () => {
  const digest = vi.fn()
  const update = vi.fn()
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubEnv('PLAYWRIGHT_SERVER_MODE', 'production')
    digest.mockReturnValue(LEGACY_SETTINGS_REACT_SHA256)
    update.mockReturnValue({ digest })
    vi.mocked(createHash).mockReturnValue({ update } as unknown as ReturnType<typeof createHash>)
  })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs() })

  it('observes the exact original case before navigation and preserves every behavior gate', () => {
    const fixture = readFileSync(new URL('../../e2e/settings-legacy-callback-owner-isolation.spec.ts', import.meta.url), 'utf8')
    const target = fixture.slice(fixture.indexOf("test('same-owner GitHub legacy callback succeeds after the session token rotates'"), fixture.indexOf("test('already-dispatched GitHub legacy verification survives"))
    expect(fixture).toContain("import { test } from './helpers/owner-isolation-hydration-fixture'")
    expect(target.indexOf('ownerIsolationHydration.requireDocuments(2)')).toBeLessThan(target.indexOf('await page.goto'))
    expect(target).not.toContain('process.env.LEGACY_SETTINGS_HYDRATION_DIAGNOSTICS')
    expect(target).toContain('await assertFixtureClean(fixture)')
    expect(target).not.toContain('installLegacySettingsHydrationDiagnostics')
    expect(target).not.toContain('finally')
    const shared = readFileSync(new URL('../../e2e/helpers/owner-isolation-hydration-fixture.ts', import.meta.url), 'utf8')
    expect(shared.indexOf('installLegacySettingsHydrationDiagnostics(page, baseURL)')).toBeLessThan(shared.indexOf('await runTestBody(control)'))
    expect(shared).toContain('{ auto: true }')
    expect(shared).toContain('throw error')
    expect(shared).toContain('await diagnostics.finish(testInfo, originalFailure')
    for (const gate of ['status-github-a-1', 'AliceInitialGitHub', 'ROTATED_TOKEN_A', 'status-github-a-2', 'AliceRotatedGitHub', 'legacy-github-a', 'AliceLegacyGitHub', 'GitHub account connected successfully!', "tokenVersion: 'rotated-a'"]) expect(target).toContain(gate)
    expect(fixture).toContain('expect(fixture.pageErrors).toEqual([])')
    const helper = readFileSync(new URL('../../e2e/helpers/legacy-settings-hydration-diagnostics.ts', import.meta.url), 'utf8')
    expect(helper).not.toMatch(/route\.fetch|route\.fulfill|page\.route|addInitScript|MutationObserver|outerHTML|innerHTML|textContent|document\.cookie|localStorage|authToken|session\.token|writeFile/)
    expect(LEGACY_SETTINGS_REACT_BYTES).toBe(173133)
    expect(LEGACY_SETTINGS_REACT_SHA256).toBe('fa2c533810f6e61eaa4849afbc041758c4eb89953b7f19f71e5b3527e1748941')
  })

  it('verifies parsed source and owned resolution, captures structural data, then resumes/removes/detaches', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    expect(test.cdp.send.mock.calls.slice(0, 4)).toEqual([
      ['Page.getFrameTree'],
      ['Debugger.enable', { maxScriptsCacheSize: 173133 }],
      ['Debugger.setPauseOnExceptions', { state: 'none' }],
      ['Debugger.setBreakpointByUrl', { url: new URL(LEGACY_SETTINGS_REACT_CHUNK, BASE).href, lineNumber: 0, columnNumber: 35054 }],
    ])
    parsed(test.cdp)
    pause(test.cdp)
    await flush()
    parsed(test.cdp, 'script-2')
    await diagnostics.verifyReady(2)
    await diagnostics.finish(test.info, false)
    expect(createHash).toHaveBeenCalledWith('sha256')
    expect(update).toHaveBeenCalledWith(source)
    expect(report(test)).toMatchObject({ verified_scripts: 2, resolved_scripts: 2, capture_attempts: 1, failures: [], captures: [validCapture()] })
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.resume')
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.removeBreakpoint', { breakpointId: OWN })
    expect(test.cdp.detach).toHaveBeenCalledOnce()
    expect(test.cdp.eventNames()).toEqual([])
    expect(test.attach).toHaveBeenCalledWith('settings-hydration-structural-diagnostic', expect.objectContaining({ contentType: 'application/json' }))
    await diagnostics.dispose()
    expect(test.cdp.detach).toHaveBeenCalledOnce()
  })

  it('accepts verified green observation without claiming a captured mismatch', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    await diagnostics.verifyReady(1)
    await diagnostics.finish(test.info, false)
    expect(report(test).captures).toEqual([])
    expect(test.attachments[0]).not.toMatch(/root.?cause|mismatch.*caused/i)
  })

  it.each(['https://localhost:5184', 'http://example.invalid', 'http://user:password@localhost:5184', 'http://localhost:5184?private=yes'])('fails closed for an unowned base URL: %s', async url => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, new URL(url))
    expect(test.connect).not.toHaveBeenCalled()
    await expect(diagnostics.verifyReady(1)).rejects.toThrow('could not be verified')
    await expect(diagnostics.finish(test.info, false)).rejects.toThrow('was unavailable')
    expect(test.attachments[0]).not.toContain(url)
  })

  it.each(['hash', 'length', 'bytes'])('refuses %s drift and always resumes a matching pause', async drift => {
    const test = fake()
    if (drift === 'hash') digest.mockReturnValue('0'.repeat(64))
    if (drift === 'length') test.cdp.handlers.set('Debugger.getScriptSource', async () => ({ scriptSource: source + 'x' }))
    if (drift === 'bytes') test.cdp.handlers.set('Debugger.getScriptSource', async () => ({ scriptSource: 'é'.repeat(173133) }))
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await flush()
    await expect(diagnostics.verifyReady(1)).rejects.toThrow('could not be verified')
    await diagnostics.finish(test.info, true)
    expect(report(test).failures).toContain('pinned-script-drift')
    expect(report(test).captures).toEqual([])
    expect(test.cdp.send.mock.calls.some(([method]) => method === 'Debugger.evaluateOnCallFrame')).toBe(false)
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.resume')
    expect(test.cdp.detach).toHaveBeenCalledOnce()
    if (drift !== 'hash') expect(createHash).not.toHaveBeenCalled()
  })

  it.each([undefined, [], ['different-breakpoint']])('does not capture pauses with missing/wrong owned breakpoints: %s', async hitBreakpoints => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp, { hitBreakpoints })
    await flush()
    await diagnostics.finish(test.info, true)
    expect(report(test).captures).toEqual([])
    expect(report(test).failures).toContain('unowned-or-unexpected-pause')
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.resume')
    expect(test.cdp.send.mock.calls.some(([method]) => method === 'Debugger.evaluateOnCallFrame')).toBe(false)
  })

  it.each([
    { functionName: 'anotherFunction', scriptId: 'script-1', columnNumber: 35060 },
    { functionName: 'rD', scriptId: 'script-1', columnNumber: 35061 },
    { functionName: 'rD', scriptId: 'wrong-script', columnNumber: 35054 },
  ])('resumes but rejects an unexpected frame: %s', async frame => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp, { callFrames: [{ functionName: frame.functionName, callFrameId: 'frame', location: { scriptId: frame.scriptId, lineNumber: 0, columnNumber: frame.columnNumber } }] })
    await flush()
    await diagnostics.finish(test.info, true)
    expect(report(test).captures).toEqual([])
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.resume')
    expect(test.cdp.send.mock.calls.some(([method]) => method === 'Debugger.evaluateOnCallFrame')).toBe(false)
  })

  it('does not fetch source for a different origin/path/query or accept an unrelated resolution', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    for (const url of ['http://localhost:5184' + LEGACY_SETTINGS_REACT_CHUNK, new URL(LEGACY_SETTINGS_REACT_CHUNK, BASE).href + '?private', new URL('/_next/static/chunks/082d2186-other.js', BASE).href]) parsed(test.cdp, 'wrong', url)
    test.cdp.emit('Debugger.breakpointResolved', { breakpointId: 'unrelated', location: { scriptId: 'script-1', lineNumber: 0, columnNumber: 35054 } })
    pause(test.cdp)
    await flush()
    await expect(diagnostics.verifyReady(1)).rejects.toThrow('could not be verified')
    await diagnostics.finish(test.info, true)
    expect(test.cdp.send.mock.calls.some(([method]) => method === 'Debugger.getScriptSource')).toBe(false)
    expect(report(test).verified_scripts).toBe(0)
  })

  it('defensively reconstructs only allowlisted structural values from hostile CDP JSON', async () => {
    const test = fake()
    const secret = 'SECRET-private-user-token-url-html'
    test.cdp.handlers.set('Debugger.evaluateOnCallFrame', async () => ({ result: { value: {
      ...validCapture(), expected: { type: secret, idCategory: secret, props: secret },
      candidate: { nodeType: 999, nodeName: secret, idCategory: secret, boundaryCommentKind: secret, text: secret },
      parentFiberTag: secret, fibers: [{ tag: -1, type: secret, user: secret }],
      source: secret, token: secret, url: secret, raw: 'x'.repeat(1000000),
    } } }))
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await flush()
    await diagnostics.finish(test.info, true)
    expect(test.attachments[0]).not.toContain(secret)
    expect(test.attachments[0].length).toBeLessThan(16384)
    expect(report(test).captures).toEqual([{ ...validCapture(), expected: { type: 'other', idCategory: 'other' }, candidate: { nodeType: null, nodeName: 'other-node', idCategory: 'other', boundaryCommentKind: null }, parentFiberTag: 'other', fibers: [{ tag: null, type: 'other' }] }])
  })

  it('bounds the expression fiber walk and reads no function names, text, or arbitrary props', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await flush()
    const params = test.cdp.send.mock.calls.find(([method]) => method === 'Debugger.evaluateOnCallFrame')?.[1]
    const expression = params?.expression as string
    expect(params).toMatchObject({ returnByValue: true, silent: true, throwOnSideEffect: true, timeout: 250 })
    const props = { id: 'main-content', get privateValue() { throw new Error('Unapproved prop read') } }
    const fiber: Record<string, unknown> = { type: 'main', tag: 5, pendingProps: props }
    fiber.return = fiber
    const node = { nodeType: 8, nodeName: '#comment', nodeValue: '$?', get textContent() { throw new Error('Unapproved text read') }, parentNode: { nodeType: 1, nodeName: 'MAIN', id: 'main-content' }, nextSibling: null }
    const evaluate = new Function('e', 'rN', 'rP', `return ${expression}`)
    const captured = evaluate(fiber, node, fiber)
    expect(captured.fibers).toHaveLength(24)
    expect(captured.expected).toEqual({ type: 'main', idCategory: 'main-content' })
    expect(captured.candidate.boundaryCommentKind).toBe('suspense-pending')
    expect(captured.parent.nodeName).toBe('main')
    await diagnostics.finish(test.info, true)
  })

  it('rejects oversized/malformed capture shapes and does not expose evaluation exceptions', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    for (const value of [null, { expected: {}, fibers: Array(25).fill({ tag: 5, type: 'main' }) }, 'SECRET-raw-json']) {
      test.cdp.handlers.set('Debugger.evaluateOnCallFrame', async () => ({ result: { value } }))
      pause(test.cdp)
      await flush()
    }
    test.cdp.handlers.set('Debugger.evaluateOnCallFrame', async () => ({ result: {}, exceptionDetails: { text: 'SECRET-exception-message', exception: { description: 'SECRET-source' } } }))
    pause(test.cdp)
    await flush()
    await diagnostics.finish(test.info, true)
    expect(report(test).captures).toEqual([])
    expect(report(test).failures).toContain('structural-evaluation-unavailable')
    expect(test.attachments[0]).not.toContain('SECRET')
    expect(test.cdp.send.mock.calls.filter(([method]) => method === 'Debugger.resume')).toHaveLength(4)
  })

  it('caps captures at eight and removes exactly its owned breakpoint', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    for (let index = 0; index < 20; index++) { pause(test.cdp); await flush() }
    await diagnostics.finish(test.info, true)
    expect(report(test).captures).toHaveLength(8)
    expect(report(test).capture_attempts).toBe(8)
    expect(test.cdp.send.mock.calls.filter(([method]) => method === 'Debugger.evaluateOnCallFrame')).toHaveLength(8)
    expect(test.cdp.send.mock.calls.filter(([method]) => method === 'Debugger.removeBreakpoint')).toEqual([['Debugger.removeBreakpoint', { breakpointId: OWN }]])
  })

  it('bounds a stalled evaluation, resumes, and ignores its eventual raw result', async () => {
    vi.useFakeTimers()
    const test = fake()
    const evaluation = deferred<unknown>()
    test.cdp.handlers.set('Debugger.evaluateOnCallFrame', () => evaluation.promise)
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await flush()
    await vi.advanceTimersByTimeAsync(251)
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.resume')
    evaluation.resolve({ result: { value: validCapture() } })
    await flush()
    await diagnostics.finish(test.info, true)
    expect(report(test).captures).toEqual([])
    expect(report(test).failures).toContain('structural-capture-unavailable')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('bounds stalled source verification and resumes without an evaluation', async () => {
    vi.useFakeTimers()
    const test = fake()
    test.cdp.handlers.set('Debugger.getScriptSource', () => new Promise(() => {}))
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await vi.advanceTimersByTimeAsync(251)
    await diagnostics.finish(test.info, true)
    expect(report(test).failures).toContain('script-verification-unavailable')
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.resume')
    expect(test.cdp.send.mock.calls.some(([method]) => method === 'Debugger.evaluateOnCallFrame')).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('waits for an already-started script verification while the owned breakpoint is paused', async () => {
    vi.useFakeTimers()
    const test = fake()
    const checking = deferred<unknown>()
    test.cdp.handlers.set('Debugger.getScriptSource', () => checking.promise)
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await vi.advanceTimersByTimeAsync(150)
    expect(test.cdp.send.mock.calls.some(([method]) => method === 'Debugger.evaluateOnCallFrame')).toBe(false)
    checking.resolve({ scriptSource: source })
    await flush()
    await diagnostics.verifyReady(1)
    await diagnostics.finish(test.info, false)
    expect(report(test).captures).toEqual([validCapture()])
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.resume')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('serializes finally/dispose resume attempts and tolerates an observed already-resumed rejection', async () => {
    const test = fake()
    const continuing = deferred<unknown>()
    test.cdp.handlers.set('Debugger.resume', () => continuing.promise)
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await flush()
    const disposing = diagnostics.dispose()
    await flush()
    expect(test.cdp.send.mock.calls.filter(([method]) => method === 'Debugger.resume')).toHaveLength(1)
    test.cdp.emit('Debugger.resumed', {})
    // A protocol rejection here means the independently observed resume won.
    continuing.resolve(Promise.reject(new Error('SECRET-already-resumed')))
    await disposing
    await diagnostics.finish(test.info, true)
    expect(test.close).not.toHaveBeenCalled()
    expect(report(test).failures).toEqual([])
    expect(test.attachments[0]).not.toContain('SECRET')
  })

  it('does not close a healthy target after a detach completes beyond its command deadline', async () => {
    vi.useFakeTimers()
    const test = fake()
    const disconnecting = deferred<void>()
    test.cdp.handlers.set('Debugger.resume', async () => { throw new Error('SECRET-resume') })
    test.cdp.detach.mockImplementation(() => disconnecting.promise)
    test.cdp.handlers.set('Debugger.disable', () => new Promise(() => {}))
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await vi.advanceTimersByTimeAsync(300)
    disconnecting.resolve()
    await vi.advanceTimersByTimeAsync(251)
    await diagnostics.finish(test.info, true)
    expect(test.close).not.toHaveBeenCalled()
    expect(report(test).failures).not.toContain('target-closed-by-diagnostic')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('resumes a new pause arriving before an older resume command result settles', async () => {
    vi.useFakeTimers()
    const test = fake()
    const firstResume = deferred<unknown>()
    let calls = 0
    test.cdp.handlers.set('Debugger.resume', () => ++calls === 1 ? firstResume.promise : Promise.resolve({}))
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await flush()
    test.cdp.emit('Debugger.resumed', {})
    pause(test.cdp)
    await flush()
    expect(calls).toBe(1)
    firstResume.resolve({})
    await flush()
    expect(calls).toBe(2)
    await diagnostics.verifyReady(1)
    await diagnostics.finish(test.info, false)
    expect(report(test).captures).toHaveLength(2)
    expect(report(test).failures).toEqual([])
    expect(test.close).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('cannot finish an otherwise green case with empty diagnostic proof', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    await expect(diagnostics.finish(test.info, false)).rejects.toThrow('was unavailable')
    expect(report(test).captures).toEqual([])
    expect(report(test).verified_scripts).toBe(0)
  })

  it('stops an older timed-out resume fallback when a new pause needs its own resume', async () => {
    vi.useFakeTimers()
    const test = fake()
    const firstResume = deferred<unknown>()
    const removing = deferred<unknown>()
    let calls = 0
    test.cdp.handlers.set('Debugger.resume', () => ++calls === 1 ? firstResume.promise : Promise.resolve({}))
    test.cdp.handlers.set('Debugger.removeBreakpoint', () => removing.promise)
    test.cdp.handlers.set('Debugger.disable', () => new Promise(() => {}))
    test.cdp.detach.mockImplementation(() => new Promise(() => {}))
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await vi.advanceTimersByTimeAsync(251)
    test.cdp.emit('Debugger.resumed', {})
    pause(test.cdp)
    await flush()
    firstResume.resolve({})
    removing.resolve({})
    await flush()
    expect(calls).toBe(2)
    expect(test.close).not.toHaveBeenCalled()
    expect(test.cdp.detach).not.toHaveBeenCalled()
    expect(test.cdp.send.mock.calls.some(([method]) => method === 'Debugger.disable')).toBe(false)
    test.cdp.detach.mockResolvedValue()
    await diagnostics.finish(test.info, true)
    expect(report(test).failures).toContain('resume-unavailable')
    expect(report(test).captures).toHaveLength(2)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('fails closed when setup returns no breakpoint or a wrong location', async () => {
    for (const breakpoint of [{ breakpointId: '', locations: [] }, { breakpointId: OWN, locations: [{ scriptId: 'script-1', lineNumber: 0, columnNumber: 35061 }] }]) {
      const test = fake()
      test.cdp.handlers.set('Debugger.setBreakpointByUrl', async () => breakpoint)
      const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
      await expect(diagnostics.verifyReady(1)).rejects.toThrow('could not be verified')
      await diagnostics.finish(test.info, true)
      expect(report(test).failures.length).toBeGreaterThan(0)
      expect(test.cdp.detach).toHaveBeenCalledOnce()
    }
  })

  it('removes a late-owned breakpoint after a timed-out setup and detaches', async () => {
    vi.useFakeTimers()
    const test = fake()
    const setting = deferred<unknown>()
    test.cdp.handlers.set('Debugger.setBreakpointByUrl', () => setting.promise)
    const installing = installLegacySettingsHydrationDiagnostics(test.page, BASE)
    await flush()
    await vi.advanceTimersByTimeAsync(2001)
    const diagnostics = await installing
    setting.resolve({ breakpointId: 'late-owned', locations: [] })
    await flush()
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.removeBreakpoint', { breakpointId: 'late-owned' })
    expect(test.cdp.detach).toHaveBeenCalledOnce()
    await diagnostics.finish(test.info, true)
    expect(report(test).failures).toContain('diagnostic-install-unavailable')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('detaches a session that connects after the bounded install has failed', async () => {
    vi.useFakeTimers()
    const test = fake()
    const connecting = deferred<FakeCDP>()
    test.connect.mockImplementation(() => connecting.promise)
    const installing = installLegacySettingsHydrationDiagnostics(test.page, BASE)
    await vi.advanceTimersByTimeAsync(2001)
    const diagnostics = await installing
    connecting.resolve(test.cdp)
    await flush()
    expect(test.cdp.detach).toHaveBeenCalledOnce()
    await diagnostics.finish(test.info, true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('fails closed after a bounded wait when no matching parsed/resolved script arrives', async () => {
    vi.useFakeTimers()
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    const verifying = expect(diagnostics.verifyReady(1)).rejects.toThrow('could not be verified')
    await vi.advanceTimersByTimeAsync(2001)
    await verifying
    await diagnostics.finish(test.info, true)
    expect(report(test).failures).toContain('diagnostic-verification-unavailable')
    await vi.advanceTimersByTimeAsync(20)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('attempts independent cleanup and preserves the exact original assertion on cleanup/attach failures', async () => {
    const test = fake()
    const original = new Error('original fixture assertion')
    test.cdp.handlers.set('Debugger.removeBreakpoint', async () => { throw new Error('SECRET-cleanup') })
    test.cdp.detach.mockRejectedValue(new Error('SECRET-detach'))
    test.attach.mockRejectedValue(new Error('SECRET-attachment'))
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    const run = async () => {
      let failed = false
      try { throw original } catch (error) { failed = true; throw error } finally { await diagnostics.finish(test.info, failed) }
    }
    await expect(run()).rejects.toBe(original)
    expect(test.cdp.send).toHaveBeenCalledWith('Debugger.removeBreakpoint', { breakpointId: OWN })
    expect(test.cdp.detach).toHaveBeenCalledOnce()
    expect(test.attach).toHaveBeenCalledOnce()
  })

  it('bounds resume/removal/detach failure and closes an otherwise orphaned paused target', async () => {
    vi.useFakeTimers()
    const test = fake()
    for (const command of ['Debugger.resume', 'Debugger.removeBreakpoint', 'Debugger.disable']) test.cdp.handlers.set(command, () => new Promise(() => {}))
    test.cdp.detach.mockImplementation(() => new Promise(() => {}))
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await vi.advanceTimersByTimeAsync(1100)
    expect(test.close).toHaveBeenCalledWith({ runBeforeUnload: false })
    const finishing = diagnostics.finish(test.info, true)
    await vi.advanceTimersByTimeAsync(1500)
    await finishing
    expect(report(test).failures).toEqual(expect.arrayContaining(['resume-unavailable', 'breakpoint-cleanup-unavailable', 'detach-unavailable', 'target-closed-by-diagnostic']))
    expect(report(test).observation_status).toBe('unavailable')
    expect(report(test).scope).toContain('no evidence of the original React throw')
    expect(test.attachments[0]).not.toContain('SECRET')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('shares one automatic primary-page observer across all cases in both test families', () => {
    const settings = readFileSync(new URL('../../e2e/settings-legacy-callback-owner-isolation.spec.ts', import.meta.url), 'utf8')
    const onboarding = readFileSync(new URL('../../e2e/onboarding-owner-isolation.spec.ts', import.meta.url), 'utf8')
    for (const fixture of [settings, onboarding]) {
      expect(fixture).toContain("import { test } from './helpers/owner-isolation-hydration-fixture'")
      expect(fixture).not.toContain('installLegacySettingsHydrationDiagnostics')
      expect(fixture).not.toContain('diagnostics.finish')
      expect(fixture).not.toContain('HYDRATION_DIAGNOSTICS')
    }
    expect(settings.match(/ownerIsolationHydration.requireDocuments\(2\)/g)).toHaveLength(1)
    expect(onboarding.match(/ownerIsolationHydration.requireDocuments\(2\)/g)).toHaveLength(1)
    expect(settings.match(/ownerIsolationHydration.expectSyntheticOpenerOnly\(\)/g)).toHaveLength(7)
    expect(onboarding).not.toContain('expectSyntheticOpenerOnly')
    const guard = onboarding.slice(onboarding.indexOf("test('fixture rejects external lookalikes"))
    expect(guard).toContain("await page.goto('/workspace'")
    expect(guard).toContain('expect(state.pageErrors).toEqual([])')
  })

  it('counts successful owned main-frame HTML documents, never SPA/subframe/API/redirect traffic', () => {
    const test = fake()
    expect(mainDocumentKind(test.page, htmlResponse(test.page), BASE)).toBe('app')
    expect(mainDocumentKind(test.page, htmlResponse(test.page, new URL('/settings?github=connected', BASE).href), BASE)).toBe('app')
    expect(mainDocumentKind(test.page, htmlResponse(test.page, new URL('/__legacy-callback-test-opener?callback=zotero', BASE).href), BASE)).toBe('synthetic-opener')
    for (const response of [
      htmlResponse(test.page, new URL('/api/auth/get-session', BASE).href),
      htmlResponse(test.page, new URL('/settings', 'http://localhost:5184').href),
      htmlResponse(test.page, undefined, { frame: {} }),
      htmlResponse(test.page, undefined, { navigation: false }),
      htmlResponse(test.page, undefined, { resourceType: 'fetch' }),
      htmlResponse(test.page, undefined, { status: 302 }),
      htmlResponse(test.page, undefined, { status: 500 }),
      htmlResponse(test.page, undefined, { contentType: 'application/json' }),
    ]) expect(mainDocumentKind(test.page, response, BASE)).toBeNull()
  })

  it('installs before the shared test body and verifies one primary document on teardown', async () => {
    const test = fake()
    await runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async () => {
      expect(test.cdp.send).toHaveBeenCalledWith('Debugger.setBreakpointByUrl', expect.any(Object))
      respond(test.page, htmlResponse(test.page))
      parsed(test.cdp)
    })
    expect(report(test)).toMatchObject({ expected_main_documents: 1, successful_main_app_documents: 1, verified_documents: 1, failures: [] })
    expect(test.cdp.detach).toHaveBeenCalledOnce()
    expect((test.page as unknown as EventEmitter).listenerCount('response')).toBe(0)
  })

  it.each([undefined, 'development'])('leaves development behavior unchanged without production proof: %s', async mode => {
    vi.stubEnv('PLAYWRIGHT_SERVER_MODE', mode)
    const test = fake()
    const body = vi.fn(async (control: { requireDocuments: (minimum: 1 | 2) => void; expectSyntheticOpenerOnly: () => void }) => {
      control.requireDocuments(2)
      control.expectSyntheticOpenerOnly()
    })
    await runOwnerIsolationHydrationFixture(test.page, BASE, test.info, body)
    expect(body).toHaveBeenCalledOnce()
    expect(test.connect).not.toHaveBeenCalled()
    expect(test.cdp.send).not.toHaveBeenCalled()
    expect(test.attach).not.toHaveBeenCalled()
    expect((test.page as unknown as EventEmitter).listenerCount('response')).toBe(0)
  })

  it('never bypasses a missing production observer after a successful app navigation', async () => {
    const test = fake()
    test.connect.mockRejectedValue(new Error('SECRET-production-CDP'))
    await expect(runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async () => {
      respond(test.page, htmlResponse(test.page))
    })).rejects.toThrow('could not be verified')
    expect(report(test).observation_status).toBe('unavailable')
    expect(report(test).failures).toContain('diagnostic-install-unavailable')
    expect(test.attachments[0]).not.toContain('SECRET')
  })

  it('requires two distinct default-main-frame contexts for the two-document cases', async () => {
    const test = fake()
    await runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async control => {
      control.requireDocuments(2)
      respond(test.page, htmlResponse(test.page))
      parsed(test.cdp)
      respond(test.page, htmlResponse(test.page))
      parsed(test.cdp, 'script-2')
    })
    expect(report(test)).toMatchObject({ expected_main_documents: 2, successful_main_app_documents: 2, verified_documents: 2 })
  })

  it('does not turn a duplicate parse in one context into two verified documents', async () => {
    vi.useFakeTimers()
    const test = fake()
    const running = expect(runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async control => {
      control.requireDocuments(2)
      respond(test.page, htmlResponse(test.page))
      respond(test.page, htmlResponse(test.page))
      parsed(test.cdp)
      parsed(test.cdp, 'duplicate-in-same-context')
    })).rejects.toThrow('could not be verified')
    await vi.advanceTimersByTimeAsync(2001)
    await running
    expect(report(test).verified_scripts).toBe(2)
    expect(report(test).verified_documents).toBe(1)
    expect(report(test).observation_status).toBe('unavailable')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('cannot substitute iframe or isolated-world React parses for a missing main document', async () => {
    vi.useFakeTimers()
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    for (const [scriptId, context] of [
      ['iframe-script', { frameId: 'child-frame', isDefault: true }],
      ['isolated-script', { frameId: 'main-frame', isDefault: false, type: 'isolated' }],
      ['contradictory-world', { frameId: 'main-frame', isDefault: false, type: 'default' }],
    ] as const) {
      test.cdp.emit('Debugger.scriptParsed', { scriptId, url: new URL(LEGACY_SETTINGS_REACT_CHUNK, BASE).href, executionContextId: 2, executionContextAuxData: context })
      test.cdp.emit('Debugger.breakpointResolved', { breakpointId: OWN, location: { scriptId, lineNumber: 0, columnNumber: 35060 } })
    }
    const verifying = expect(diagnostics.verifyReady(2)).rejects.toThrow('could not be verified')
    await vi.advanceTimersByTimeAsync(2001)
    await verifying
    await diagnostics.finish(test.info, true)
    expect(report(test).verified_documents).toBe(1)
    expect(test.cdp.send.mock.calls.filter(([method]) => method === 'Debugger.getScriptSource')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(20)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('rejects missing app document responses despite a verified React script', async () => {
    const test = fake()
    await expect(runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async () => { parsed(test.cdp) })).rejects.toThrow('Required main app documents')
    expect(report(test).failures).toContain('main-document-observation-unavailable')
    expect(report(test).observation_status).toBe('unavailable')
  })

  it('reports explicit synthetic-opener-only scope without hydration or popup evidence', async () => {
    const test = fake()
    await runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async control => {
      control.expectSyntheticOpenerOnly()
      respond(test.page, htmlResponse(test.page, new URL('/__legacy-callback-test-opener?callback=zotero', BASE).href))
    })
    expect(report(test)).toMatchObject({ expected_main_documents: 0, successful_main_app_documents: 0, verified_documents: 0, failures: [], captures: [], observation_status: 'outside-scope-synthetic-opener-only' })
    expect(report(test).scope).toContain('popup hydration capture outside scope')
  })

  it('never uses synthetic-opener scope to excuse app navigation or an absent opener', async () => {
    for (const appNavigation of [false, true]) {
      const test = fake()
      await expect(runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async control => {
        control.expectSyntheticOpenerOnly()
        if (appNavigation) {
          respond(test.page, htmlResponse(test.page))
          parsed(test.cdp)
        }
      })).rejects.toThrow('Synthetic-opener-only hydration scope')
      expect(report(test).failures).toContain('main-document-observation-unavailable')
      expect(report(test).observation_status).toBe('unavailable')
    }
  })

  it('preserves original shared-fixture assertion errors when cleanup/attachment also fail', async () => {
    const test = fake()
    const original = new Error('original shared-fixture assertion')
    test.cdp.handlers.set('Debugger.removeBreakpoint', async () => { throw new Error('SECRET-cleanup') })
    test.attach.mockRejectedValue(new Error('SECRET-attachment'))
    await expect(runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async () => { throw original })).rejects.toBe(original)
    expect(test.cdp.detach).toHaveBeenCalledOnce()
    expect(test.attach).toHaveBeenCalledOnce()
  })

  it('honors Playwright failed status even if use() resolves during fixture teardown', async () => {
    const test = fake()
    test.info.status = 'failed'
    await runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async () => {})
    expect(report(test).observation_status).toBe('unavailable')
    expect(test.cdp.detach).toHaveBeenCalledOnce()
  })

  it.each([false, true])('reports failed two-document cases unavailable with only one verified generation (explicit: %s)', async explicit => {
    const test = fake()
    test.info.status = 'failed'
    await runOwnerIsolationHydrationFixture(test.page, BASE, test.info, async control => {
      if (explicit) control.requireDocuments(2)
      respond(test.page, htmlResponse(test.page))
      parsed(test.cdp)
      await flush()
      respond(test.page, htmlResponse(test.page))
    })
    expect(report(test)).toMatchObject({ expected_main_documents: 2, successful_main_app_documents: 2, verified_documents: 1, observation_status: 'unavailable' })
    expect(report(test).failures).toContain('diagnostic-proof-unavailable')
    expect(test.cdp.detach).toHaveBeenCalledOnce()
  })

  it('classifies exact $~ structurally, redacts arbitrary comments, and captures identity flags', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    parsed(test.cdp)
    pause(test.cdp)
    await flush()
    const expression = test.cdp.send.mock.calls.find(([method]) => method === 'Debugger.evaluateOnCallFrame')?.[1]?.expression as string
    const evaluate = new Function('e', 'rN', 'rP', `return ${expression}`)
    const fiber = { type: 'main', tag: 5, pendingProps: { id: 'main-content' }, alternate: { private: 'SECRET-alternate' }, return: null }
    const result = evaluate(fiber, { nodeType: 8, nodeName: '#comment', nodeValue: '$~' }, fiber)
    expect(result.candidate.boundaryCommentKind).toBe('suspense-streaming')
    expect(result.hydrationParentIsExpected).toBe(true)
    expect(result.alternatePresent).toBe(true)
    expect(result.fibers[0].tag).toBe(5)
    const different = evaluate({ ...fiber, alternate: null }, { nodeType: 8, nodeName: '#comment', nodeValue: '$~SECRET-comment' }, fiber)
    expect(different.candidate.boundaryCommentKind).toBe('other-comment')
    expect(different.hydrationParentIsExpected).toBe(false)
    expect(different.alternatePresent).toBe(false)
    expect(JSON.stringify([result, different])).not.toContain('SECRET')
    test.cdp.handlers.set('Debugger.evaluateOnCallFrame', async () => ({ result: { value: { ...result, rawComment: 'SECRET-comment' } } }))
    pause(test.cdp)
    await flush()
    await diagnostics.finish(test.info, true)
    expect(report(test).captures[1]).toMatchObject({ candidate: { boundaryCommentKind: 'suspense-streaming' }, hydrationParentIsExpected: true, alternatePresent: true })
    expect(test.attachments[0]).not.toContain('SECRET')
  })

  it.each([undefined, null, 0, 1, 'true', 'SECRET-identity'])('rejects non-boolean identity flags: %s', async value => {
    for (const field of ['hydrationParentIsExpected', 'alternatePresent']) {
      const test = fake()
      test.cdp.handlers.set('Debugger.evaluateOnCallFrame', async () => ({ result: { value: { ...validCapture(), [field]: value } } }))
      const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
      parsed(test.cdp)
      pause(test.cdp)
      await flush()
      await diagnostics.finish(test.info, true)
      expect(report(test).captures).toEqual([])
      expect(report(test).failures).toContain('structural-result-unavailable')
      expect(test.cdp.send).toHaveBeenCalledWith('Debugger.resume')
      expect(test.attachments[0]).not.toContain('SECRET')
    }
  })

})
