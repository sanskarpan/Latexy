import { readFileSync } from 'node:fs'
import { EventEmitter } from 'node:events'
import { createHash } from 'node:crypto'
import type { Page, TestInfo } from '@playwright/test'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installLegacySettingsHydrationDiagnostics, LEGACY_SETTINGS_REACT_BYTES, LEGACY_SETTINGS_REACT_CHUNK, LEGACY_SETTINGS_REACT_SHA256 } from '../../e2e/helpers/legacy-settings-hydration-diagnostics'

vi.mock('node:crypto', () => ({ createHash: vi.fn() }))
const BASE = new URL('http://127.0.0.1:5184')
const OWN = 'owned-breakpoint'
const source = ' '.repeat(173025)
const validCapture = () => ({
  expected: { type: 'main', idCategory: 'main-content' },
  candidate: { nodeType: 8, nodeName: '#comment', idCategory: 'none', boundaryCommentKind: 'suspense-pending' },
  parent: { nodeType: 1, nodeName: 'main', idCategory: 'main-content', boundaryCommentKind: null },
  next: { nodeType: 1, nodeName: 'div', idCategory: 'none', boundaryCommentKind: null },
  parentFiberTag: 'main', fibers: [{ tag: 5, type: 'main' }, { tag: 0, type: 'function' }],
})
type Handler = (params: Record<string, unknown>) => Promise<unknown>
class FakeCDP extends EventEmitter {
  handlers = new Map<string, Handler>()
  send = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    const handler = this.handlers.get(method)
    if (handler) return handler(params)
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
  const page = { context: () => ({ newCDPSession: connect }), close } as unknown as Page
  const attachments: string[] = []
  const attach = vi.fn(async (_name: string, options: { body: Buffer }) => { attachments.push(options.body.toString()) })
  const info = { attach } as unknown as TestInfo
  return { cdp, page, connect, close, info, attach, attachments }
}
function parsed(cdp: FakeCDP, scriptId = 'script-1', url = new URL(LEGACY_SETTINGS_REACT_CHUNK, BASE).href) {
  cdp.emit('Debugger.scriptParsed', { scriptId, url })
  cdp.emit('Debugger.breakpointResolved', { breakpointId: OWN, location: { scriptId, lineNumber: 0, columnNumber: 35061 } })
}
function pause(cdp: FakeCDP, overrides: Record<string, unknown> = {}) {
  cdp.emit('Debugger.paused', {
    callFrames: [{ functionName: 'rD', callFrameId: 'frame', location: { scriptId: 'script-1', lineNumber: 0, columnNumber: 35061 } }],
    hitBreakpoints: [OWN], reason: 'other', ...overrides,
  })
}
async function flush() { for (let index = 0; index < 40; index++) await Promise.resolve() }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
function report(test: ReturnType<typeof fake>) { return JSON.parse(test.attachments[0]) as { captures: unknown[]; failures: string[]; verified_scripts: number; resolved_scripts: number; capture_attempts: number; observation_status: string; scope: string } }

describe('original-case CDP Settings hydration diagnostic', () => {
  const digest = vi.fn()
  const update = vi.fn()
  beforeEach(() => {
    vi.clearAllMocks()
    digest.mockReturnValue(LEGACY_SETTINGS_REACT_SHA256)
    update.mockReturnValue({ digest })
    vi.mocked(createHash).mockReturnValue({ update } as unknown as ReturnType<typeof createHash>)
  })
  afterEach(() => { vi.useRealTimers() })

  it('observes the exact original case before navigation and preserves every behavior gate', () => {
    const fixture = readFileSync(new URL('../../e2e/settings-legacy-callback-owner-isolation.spec.ts', import.meta.url), 'utf8')
    const target = fixture.slice(fixture.indexOf("test('same-owner GitHub legacy callback succeeds after the session token rotates'"), fixture.indexOf("test('already-dispatched GitHub legacy verification survives"))
    expect(target.indexOf('installLegacySettingsHydrationDiagnostics(page, appBaseUrl())')).toBeLessThan(target.indexOf('await page.goto'))
    expect(target).not.toContain('process.env.LEGACY_SETTINGS_HYDRATION_DIAGNOSTICS')
    expect(target).toContain('await assertFixtureClean(fixture)')
    expect(target).toContain('await diagnostics.verifyReady(2)')
    expect(target).toContain('throw error')
    expect(target).toContain('finally {\n      await diagnostics.finish(testInfo, originalFailure)')
    for (const gate of ['status-github-a-1', 'AliceInitialGitHub', 'ROTATED_TOKEN_A', 'status-github-a-2', 'AliceRotatedGitHub', 'legacy-github-a', 'AliceLegacyGitHub', 'GitHub account connected successfully!', "tokenVersion: 'rotated-a'"]) expect(target).toContain(gate)
    expect(fixture).toContain('expect(fixture.pageErrors).toEqual([])')
    const helper = readFileSync(new URL('../../e2e/helpers/legacy-settings-hydration-diagnostics.ts', import.meta.url), 'utf8')
    expect(helper).not.toMatch(/route\.fetch|route\.fulfill|page\.route|addInitScript|MutationObserver|outerHTML|innerHTML|textContent|document\.cookie|localStorage|authToken|session\.token|writeFile/)
    expect(LEGACY_SETTINGS_REACT_BYTES).toBe(173025)
    expect(LEGACY_SETTINGS_REACT_SHA256).toBe('a0e4c895093e4f49edffedacbeca356d139ebced5a1f3b68cd5783f6a94388b3')
  })

  it('verifies parsed source and owned resolution, captures structural data, then resumes/removes/detaches', async () => {
    const test = fake()
    const diagnostics = await installLegacySettingsHydrationDiagnostics(test.page, BASE)
    expect(test.cdp.send.mock.calls.slice(0, 3)).toEqual([
      ['Debugger.enable', { maxScriptsCacheSize: 173025 }],
      ['Debugger.setPauseOnExceptions', { state: 'none' }],
      ['Debugger.setBreakpointByUrl', { url: new URL(LEGACY_SETTINGS_REACT_CHUNK, BASE).href, lineNumber: 0, columnNumber: 35055 }],
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
    if (drift === 'bytes') test.cdp.handlers.set('Debugger.getScriptSource', async () => ({ scriptSource: 'é'.repeat(173025) }))
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
    { functionName: 'anotherFunction', scriptId: 'script-1', columnNumber: 35061 },
    { functionName: 'rD', scriptId: 'script-1', columnNumber: 35062 },
    { functionName: 'rD', scriptId: 'wrong-script', columnNumber: 35055 },
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
    test.cdp.emit('Debugger.breakpointResolved', { breakpointId: 'unrelated', location: { scriptId: 'script-1', lineNumber: 0, columnNumber: 35055 } })
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
    for (const breakpoint of [{ breakpointId: '', locations: [] }, { breakpointId: OWN, locations: [{ scriptId: 'script-1', lineNumber: 0, columnNumber: 35062 }] }]) {
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
})
