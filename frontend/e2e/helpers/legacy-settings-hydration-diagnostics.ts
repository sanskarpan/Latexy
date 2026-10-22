import type { CDPSession, Page, TestInfo } from '@playwright/test'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'

// Test-only CDP observer: never rewrite a response or guess another React hook.
// Exact normal-channel production bundle after the reviewed Next 15.5.27
// host-replay backport. rD(e), rN (cursor), and rP (parent) retain their roles.
export const LEGACY_SETTINGS_REACT_CHUNK = '/_next/static/chunks/acabd415-aedf19c35bd5be5e.js'
export const LEGACY_SETTINGS_REACT_SHA256 = 'fa2c533810f6e61eaa4849afbc041758c4eb89953b7f19f71e5b3527e1748941'
export const LEGACY_SETTINGS_REACT_BYTES = 173133
const CLAIM_LOCATION = { lineNumber: 0, columnNumber: 35054 } as const
const COMMAND_TIMEOUT_MS = 250
const SETUP_TIMEOUT_MS = 2000
const PAUSE_WATCHDOG_MS = 1000
const VERIFY_TIMEOUT_MS = 2000
const MAX_CAPTURES = 8
const MAX_FIBERS = 24
// Evidence only: this observed CI candidate is not a second trusted pin.
const CANDIDATE_SCRIPT = '/_next/static/chunks/630253d5-0ac8e4a42daf72ba.js'
const MAX_CANDIDATE_BYTES = 200_000
const HOST_TAGS = 'a abbr address area article aside audio b base bdi bdo blockquote body br button canvas caption circle cite clippath code col colgroup data datalist dd defs del details dfn dialog div dl dt ellipse em embed fieldset figcaption figure footer form g h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li line link main map mark mask menu meta meter nav noscript object ol optgroup option output p path picture polygon polyline pre progress q rect rp rt ruby s samp script search section select slot small source span stop strong style sub summary sup svg symbol table tbody td template text textarea tfoot th thead time title tr track tspan u ul use var video wbr'.split(' ')
const TYPE_CATEGORIES = ['function', 'symbol', 'object', 'other', 'none', 'other-host']
const ID_CATEGORIES = ['main-content', 'stream-boundary', 'other', 'none']
const NODE_NAMES = [...HOST_TAGS, '#text', '#comment', '#document', '#document-fragment']
const BOUNDARY_KINDS = ['suspense-start', 'suspense-end', 'suspense-pending', 'suspense-streaming', 'suspense-client-render', 'other-comment']

// Read only structural categories. No function names or arbitrary prop values.
// The returned CDP value is independently rebuilt below, never attached raw.
const STRUCTURAL_CAPTURE = `(() => {
  const tags = new Set(${JSON.stringify(HOST_TAGS)});
  const type = value => typeof value === 'string' ? tags.has(value.toLowerCase()) ? value.toLowerCase() : 'other-host' : value == null ? 'none' : ['function', 'symbol', 'object'].includes(typeof value) ? typeof value : 'other';
  const id = value => value === 'main-content' ? 'main-content' : typeof value === 'string' && /^[BS]:[0-9]+$/.test(value) ? 'stream-boundary' : value ? 'other' : 'none';
  const node = value => {
    if (!value) return null;
    const name = value.nodeName;
    const comment = value.nodeType === 8 ? value.nodeValue : null;
    return { nodeType: value.nodeType, nodeName: typeof name === 'string' && (tags.has(name.toLowerCase()) || ['#text', '#comment', '#document', '#document-fragment'].includes(name)) ? name.toLowerCase() : 'other-node', idCategory: id(value.id), boundaryCommentKind: value.nodeType !== 8 ? null : comment === '$' ? 'suspense-start' : comment === '/$' ? 'suspense-end' : comment === '$?' ? 'suspense-pending' : comment === '$~' ? 'suspense-streaming' : comment === '$!' ? 'suspense-client-render' : 'other-comment' };
  };
  const fibers = [];
  for (let fiber = e; fiber && fibers.length < ${MAX_FIBERS}; fiber = fiber.return) fibers.push({ tag: fiber.tag, type: type(fiber.type) });
  return { expected: { type: type(e.type), idCategory: id(e.pendingProps && e.pendingProps.id) }, candidate: node(rN), parent: node(rN && rN.parentNode), next: node(rN && rN.nextSibling), parentFiberTag: type(rP && rP.type), hydrationParentIsExpected: rP === e, alternatePresent: Boolean(e.alternate), fibers };
})()`

type NodeKind = { nodeType: number | null; nodeName: string; idCategory: string; boundaryCommentKind: string | null }
type StructuralCapture = {
  expected: { type: string; idCategory: string }
  candidate: NodeKind | null
  parent: NodeKind | null
  next: NodeKind | null
  parentFiberTag: string
  hydrationParentIsExpected: boolean
  alternatePresent: boolean
  fibers: Array<{ tag: number | null; type: string }>
}
export type MainDocumentObservation = {
  expectedDocuments: number
  successfulAppDocuments: number
  successfulSyntheticOpeners: number
  syntheticOpenerOnly: boolean
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}
function member(value: unknown, allowed: readonly string[], fallback: string): string {
  return typeof value === 'string' && allowed.includes(value) ? value : fallback
}
function hostType(value: unknown): string { return member(value, [...HOST_TAGS, ...TYPE_CATEGORIES], 'other') }
function nodeKind(value: unknown): NodeKind | null {
  const node = record(value)
  return node ? {
    nodeType: typeof node.nodeType === 'number' && Number.isInteger(node.nodeType) && node.nodeType >= 1 && node.nodeType <= 12 ? node.nodeType : null,
    nodeName: member(node.nodeName, NODE_NAMES, 'other-node'),
    idCategory: member(node.idCategory, ID_CATEGORIES, 'other'),
    boundaryCommentKind: typeof node.boundaryCommentKind === 'string' && BOUNDARY_KINDS.includes(node.boundaryCommentKind) ? node.boundaryCommentKind : null,
  } : null
}
function structuralCapture(value: unknown): StructuralCapture | null {
  const capture = record(value)
  const expected = record(capture?.expected)
  if (!capture || !expected || !Array.isArray(capture.fibers) || capture.fibers.length > MAX_FIBERS
    || typeof capture.hydrationParentIsExpected !== 'boolean' || typeof capture.alternatePresent !== 'boolean') return null
  return {
    expected: { type: hostType(expected.type), idCategory: member(expected.idCategory, ID_CATEGORIES, 'other') },
    candidate: nodeKind(capture.candidate), parent: nodeKind(capture.parent), next: nodeKind(capture.next),
    parentFiberTag: hostType(capture.parentFiberTag),
    hydrationParentIsExpected: capture.hydrationParentIsExpected,
    alternatePresent: capture.alternatePresent,
    fibers: capture.fibers.map(value => {
      const fiber = record(value)
      return { tag: typeof fiber?.tag === 'number' && Number.isInteger(fiber.tag) && fiber.tag >= 0 && fiber.tag <= 31 ? fiber.tag : null, type: hostType(fiber?.type) }
    }),
  }
}
async function deadline<T>(promise: Promise<T>, timeout = COMMAND_TIMEOUT_MS): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([promise, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error('Diagnostic command deadline exceeded')), timeout)
    })])
  } finally { clearTimeout(timer) }
}

export async function installLegacySettingsHydrationDiagnostics(page: Page, baseURL: URL) {
  const failures = new Set<string>()
  const captures: StructuralCapture[] = []
  const verifiedScripts = new Set<string>()
  const resolvedScripts = new Set<string>()
  const scriptChecks = new Map<string, Promise<boolean>>()
  const scriptContexts = new Map<string, number>()
  const activePauses = new Set<Promise<void>>()
  let session: CDPSession | null = null
  let breakpointId: string | null = null
  let pinnedURL = ''
  let mainFrameId = ''
  let disposed = false
  let detached = false
  let breakpointRemoved = false
  let captureAttempts = 0
  let paused = false
  let pauseGeneration = 0
  let resuming: Promise<void> | null = null
  let candidateRead: Promise<void> | null = null
  let candidateAttempted = false
  let candidateEvidence: { body: Buffer; manifest: Record<string, string | number> } | null = null
  const runnerContextSha = process.env.GITHUB_SHA
  const fail = (code: string) => { if (failures.size < 16) failures.add(code) }
  const verifiedDocuments = () => new Set([...verifiedScripts].filter(id => resolvedScripts.has(id)).map(id => scriptContexts.get(id))).size
  // Chrome can advance the first statement to Error(), six columns later.
  // This range stays within the reviewed rD statement of the exact hash pin.
  const locationMatches = (location: { lineNumber: number; columnNumber?: number }) => location.lineNumber === 0
    && typeof location.columnNumber === 'number' && location.columnNumber >= 35054 && location.columnNumber <= 35060

  async function removeOwnedBreakpoint(id = breakpointId) {
    if (!session || !id || breakpointRemoved) return
    try { await deadline(session.send('Debugger.removeBreakpoint', { breakpointId: id })); breakpointRemoved = true }
    catch { fail('breakpoint-cleanup-unavailable') }
  }
  async function detach() {
    if (!session || detached) return
    const disconnecting = session.detach()
    void disconnecting.then(() => { detached = true; paused = false }, () => undefined)
    try { await deadline(disconnecting); detached = true; paused = false } catch { fail('detach-unavailable') }
  }
  async function resume(generation = pauseGeneration): Promise<void> {
    if (resuming) {
      const pending = resuming
      await pending
      if (resuming === pending) resuming = null
      // A later pause can arrive before the previous command result. It needs
      // its own resume, but an old pause must not resume a newer capture early.
      if (paused && generation === pauseGeneration) await resume(generation)
      return
    }
    if (!session || detached || !paused || generation !== pauseGeneration) return
    const cdp = session
    const task = (async () => {
      try {
        const continuing = cdp.send('Debugger.resume')
        void continuing.then(() => { if (generation === pauseGeneration) paused = false }, () => undefined)
        await deadline(continuing)
        if (generation === pauseGeneration) paused = false
      } catch {
        // A resumed event can arrive before an already-resumed rejection.
        if (!paused || generation !== pauseGeneration) return
        fail('resume-unavailable')
        await removeOwnedBreakpoint()
        if (!paused || generation !== pauseGeneration) return
        await detach()
        if (!paused || generation !== pauseGeneration) return
        if (!detached && paused) {
          try {
            const disabling = cdp.send('Debugger.disable')
            void disabling.then(() => { paused = false }, () => undefined)
            await deadline(disabling)
            paused = false
          }
          catch { fail('debugger-release-unavailable') }
        }
        if (!paused || generation !== pauseGeneration) return
        if (!detached && paused) {
          // Every debugger release failed. Close only an irrecoverably paused
          // target; the diagnostic is failed and makes no mismatch claim.
          fail('target-closed-by-diagnostic')
          try { await deadline(page.close({ runBeforeUnload: false })); paused = false } catch { fail('paused-target-close-unavailable') }
        }
      }
    })()
    resuming = task
    try { await task } finally { if (resuming === task) resuming = null }
  }
  async function verifyScript(scriptId: string): Promise<boolean> {
    if (!session || disposed || detached) return false
    try {
      const { scriptSource: source } = await deadline(session.send('Debugger.getScriptSource', { scriptId }))
      if (typeof source !== 'string' || source.length > LEGACY_SETTINGS_REACT_BYTES
        || Buffer.byteLength(source) !== LEGACY_SETTINGS_REACT_BYTES
        || createHash('sha256').update(source).digest('hex') !== LEGACY_SETTINGS_REACT_SHA256) {
        fail('pinned-script-drift'); return false
      }
      if (disposed || detached) return false
      verifiedScripts.add(scriptId)
      return true
    } catch { fail('script-verification-unavailable'); return false }
  }

  // Select the installed Playwright generic protocol overload, not close.
  const pausedEvent = (cdp: CDPSession) => cdp.on<'Debugger.paused'>
  type PausedEvent = Parameters<Parameters<ReturnType<typeof pausedEvent>>[1]>[0]
  const parsedEvent = (cdp: CDPSession) => cdp.on<'Debugger.scriptParsed'>
  type ParsedEvent = Parameters<Parameters<ReturnType<typeof parsedEvent>>[1]>[0]
  const resolvedEvent = (cdp: CDPSession) => cdp.on<'Debugger.breakpointResolved'>
  type ResolvedEvent = Parameters<Parameters<ReturnType<typeof resolvedEvent>>[1]>[0]
  async function readCandidateEvidence(scriptId: string): Promise<void> {
    // Read only an already-loaded public script. Never bind its breakpoint,
    // evaluate it, or add it to any verified-script/acceptance collection.
    try {
      if (!session || !runnerContextSha || !/^[0-9a-f]{40}$/.test(runnerContextSha)) return
      const { scriptSource } = await deadline(session.send('Debugger.getScriptSource', { scriptId }), VERIFY_TIMEOUT_MS)
      if (typeof scriptSource !== 'string' || scriptSource.length > MAX_CANDIDATE_BYTES) return
      const body = Buffer.from(scriptSource)
      if (body.length === 0 || body.length > MAX_CANDIDATE_BYTES) return
      const version: unknown = createRequire(`${process.cwd()}/package.json`)('next/package.json').version
      if (typeof version !== 'string' || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version)) return
      candidateEvidence = { body, manifest: {
        status: 'unverified-candidate-script',
        // Runner context identifies this CI execution, not clean/deploy provenance.
        runner_context_sha: runnerContextSha, next_version: version,
        filename: CANDIDATE_SCRIPT.split('/').pop()!, bytes: body.length,
        sha256: createHash('sha256').update(body).digest('hex'),
      } }
    } catch { /* Optional evidence cannot replace or satisfy the existing gates. */ }
  }
  function onParsed(event: ParsedEvent) {
    if (!disposed && !detached && !candidateAttempted && pinnedURL
      && event.url === new URL(CANDIDATE_SCRIPT, baseURL.origin).href
      && runnerContextSha && /^[0-9a-f]{40}$/.test(runnerContextSha)) {
      const context = record(event.executionContextAuxData)
      if (context?.frameId === mainFrameId && context.isDefault === true
        && (context.type === undefined || context.type === 'default')
        && Number.isInteger(event.executionContextId) && event.executionContextId > 0) {
        candidateAttempted = true
        candidateRead = readCandidateEvidence(event.scriptId)
      }
    }
    if (disposed || event.url !== pinnedURL || scriptChecks.has(event.scriptId)) return
    const context = record(event.executionContextAuxData)
    if (context?.frameId !== mainFrameId || context.isDefault !== true
      || (context.type !== undefined && context.type !== 'default')) return
    if (!Number.isInteger(event.executionContextId) || event.executionContextId <= 0) { fail('script-context-unavailable'); return }
    scriptContexts.set(event.scriptId, event.executionContextId)
    scriptChecks.set(event.scriptId, verifyScript(event.scriptId))
  }
  function onResolved(event: ResolvedEvent) {
    if (disposed || event.breakpointId !== breakpointId) return
    if (locationMatches(event.location)) resolvedScripts.add(event.location.scriptId)
    else fail('breakpoint-location-drift')
  }
  function onResumed() { paused = false }
  function onSessionClose() { detached = true; paused = false }
  async function capturePause(event: PausedEvent) {
    paused = true
    const generation = ++pauseGeneration
    const cdp = session
    let watchdogFired = false
    const watchdog = setTimeout(() => {
      watchdogFired = true
      if (paused && generation === pauseGeneration) { fail('pause-watchdog-expired'); void resume(generation) }
    }, PAUSE_WATCHDOG_MS)
    try {
      const frame = event.callFrames[0]
      const owned = breakpointId && event.hitBreakpoints && event.hitBreakpoints.length <= 8 && event.hitBreakpoints.includes(breakpointId)
      if (disposed || !owned || !frame || frame.functionName !== 'rD' || !locationMatches(frame.location)) {
        if (!disposed) fail('unowned-or-unexpected-pause')
        return
      }
      if (captureAttempts >= MAX_CAPTURES) return
      captureAttempts++
      const verified = await scriptChecks.get(frame.location.scriptId)
      if (!verified || !verifiedScripts.has(frame.location.scriptId)) { fail('unverified-paused-script'); return }
      if (!cdp || disposed || watchdogFired || detached) return
      const result = await deadline(cdp.send('Debugger.evaluateOnCallFrame', {
        callFrameId: frame.callFrameId, expression: STRUCTURAL_CAPTURE,
        returnByValue: true, silent: true, throwOnSideEffect: true, timeout: COMMAND_TIMEOUT_MS,
      }))
      if (result.exceptionDetails) { fail('structural-evaluation-unavailable'); return }
      const capture = structuralCapture(result.result.value)
      if (!capture) { fail('structural-result-unavailable'); return }
      if (!disposed && !watchdogFired && !detached) captures.push(capture)
    } catch { fail('structural-capture-unavailable') } finally {
      await resume(generation)
      clearTimeout(watchdog)
      if (captureAttempts >= MAX_CAPTURES) await removeOwnedBreakpoint()
    }
  }
  function onPaused(event: PausedEvent) {
    const task = capturePause(event)
    activePauses.add(task)
    void task.finally(() => activePauses.delete(task))
  }
  async function dispose() {
    if (disposed) return
    disposed = true
    if (session) {
      if (paused) await resume()
      await removeOwnedBreakpoint()
      try { await deadline(Promise.all([...activePauses]), PAUSE_WATCHDOG_MS + COMMAND_TIMEOUT_MS) } catch { fail('pause-cleanup-unavailable') }
      await detach()
      session.off('Debugger.paused', onPaused)
      session.off('Debugger.scriptParsed', onParsed)
      session.off('Debugger.breakpointResolved', onResolved)
      session.off('Debugger.resumed', onResumed)
      session.off('close', onSessionClose)
    }
  }

  try {
    if (baseURL.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(baseURL.hostname)
      || baseURL.username || baseURL.password || baseURL.search || baseURL.hash) fail('loopback-origin-unavailable')
    else {
      pinnedURL = new URL(LEGACY_SETTINGS_REACT_CHUNK, baseURL.origin).href
      const connecting = page.context().newCDPSession(page)
      // Cleanup late completions after their caller's bounded wait has ended.
      void connecting.then(async lateSession => {
        if (disposed && session !== lateSession) {
          try { await deadline(lateSession.detach()) } catch { fail('late-session-detach-unavailable') }
        }
      }, () => undefined)
      session = await deadline(connecting, SETUP_TIMEOUT_MS)
      session.on('Debugger.paused', onPaused)
      session.on('Debugger.scriptParsed', onParsed)
      session.on('Debugger.breakpointResolved', onResolved)
      session.on('Debugger.resumed', onResumed)
      session.on('close', onSessionClose)
      const { frameTree } = await deadline(session.send('Page.getFrameTree'), SETUP_TIMEOUT_MS)
      if (!frameTree.frame.id) throw new Error('Diagnostic main frame unavailable')
      mainFrameId = frameTree.frame.id
      await deadline(session.send('Debugger.enable', { maxScriptsCacheSize: LEGACY_SETTINGS_REACT_BYTES }), SETUP_TIMEOUT_MS)
      await deadline(session.send('Debugger.setPauseOnExceptions', { state: 'none' }), SETUP_TIMEOUT_MS)
      const setting = session.send('Debugger.setBreakpointByUrl', { url: pinnedURL, ...CLAIM_LOCATION })
      void setting.then(async lateBreakpoint => {
        if (disposed && typeof lateBreakpoint.breakpointId === 'string' && lateBreakpoint.breakpointId) {
          try { await deadline(session!.send('Debugger.removeBreakpoint', { breakpointId: lateBreakpoint.breakpointId })) } catch { fail('late-breakpoint-cleanup-unavailable') }
          await detach()
        }
      }, () => undefined)
      const breakpoint = await deadline(setting, SETUP_TIMEOUT_MS)
      if (typeof breakpoint.breakpointId !== 'string' || !breakpoint.breakpointId || breakpoint.breakpointId.length > 2048) fail('breakpoint-unavailable')
      else {
        breakpointId = breakpoint.breakpointId
        if (breakpoint.locations.length > 8) fail('breakpoint-location-drift')
        else for (const location of breakpoint.locations) {
          if (locationMatches(location)) resolvedScripts.add(location.scriptId)
          else fail('breakpoint-location-drift')
        }
      }
    }
  } catch { fail('diagnostic-install-unavailable'); await dispose() }

  return {
    async verifyReady(expectedDocuments: number) {
      try {
        await deadline((async () => {
          while (!failures.size && !disposed && verifiedDocuments() < expectedDocuments) await new Promise(resolve => setTimeout(resolve, 10))
        })(), VERIFY_TIMEOUT_MS)
      } catch { fail('diagnostic-verification-unavailable') }
      if (failures.size || !breakpointId || verifiedDocuments() < expectedDocuments) throw new Error('Original-case owner-isolation hydration diagnostic could not be verified')
    },
    dispose,
    async finish(testInfo: TestInfo, originalFailure: boolean, observation?: MainDocumentObservation) {
      // Cleanup/attachment failures must never replace a behavior assertion.
      if (candidateRead) {
        try { await deadline(candidateRead, VERIFY_TIMEOUT_MS) } catch { /* Unverified evidence only. */ }
      }
      try { await dispose() } catch { fail('diagnostic-cleanup-unavailable') }
      const excluded = observation?.syntheticOpenerOnly === true && observation.expectedDocuments === 0
        && observation.successfulAppDocuments === 0 && observation.successfulSyntheticOpeners > 0 && verifiedScripts.size === 0
      const requiredDocuments = observation ? Math.max(observation.expectedDocuments, observation.successfulAppDocuments) : 1
      if (observation && (observation.syntheticOpenerOnly ? !excluded : observation.successfulAppDocuments < observation.expectedDocuments)) fail('main-document-observation-unavailable')
      if (!excluded && (!breakpointId || verifiedDocuments() < requiredDocuments)) fail('diagnostic-proof-unavailable')
      try {
        await deadline(testInfo.attach('settings-hydration-structural-diagnostic', {
          body: Buffer.from(JSON.stringify({
            scope: failures.has('target-closed-by-diagnostic')
              ? 'diagnostic recovery closed a paused target; no evidence of the original React throw'
              : 'original-case main-page-only CDP observation; production response unchanged; popup hydration capture outside scope',
            observation_status: failures.size ? 'unavailable' : excluded ? 'outside-scope-synthetic-opener-only' : captures.length ? 'structural-pause-captured' : 'no-matching-pause-observed',
            expected_main_documents: observation ? requiredDocuments : null,
            successful_main_app_documents: observation?.successfulAppDocuments ?? null,
            successful_synthetic_openers: observation?.successfulSyntheticOpeners ?? null,
            verified_documents: verifiedDocuments(),
            verified_scripts: verifiedScripts.size,
            resolved_scripts: [...verifiedScripts].filter(id => resolvedScripts.has(id)).length,
            capture_attempts: captureAttempts, failures: [...failures], captures,
          }, null, 2) + '\n'), contentType: 'application/json',
        }), VERIFY_TIMEOUT_MS)
      } catch { fail('diagnostic-attachment-unavailable') }
      if (candidateEvidence) {
        try {
          await deadline(testInfo.attach('unverified-candidate-renderer.js', {
            body: candidateEvidence.body, contentType: 'application/javascript',
          }), VERIFY_TIMEOUT_MS)
          await deadline(testInfo.attach('unverified-candidate-renderer-manifest', {
            body: Buffer.from(JSON.stringify(candidateEvidence.manifest, null, 2) + '\n'), contentType: 'application/json',
          }), VERIFY_TIMEOUT_MS)
        } catch { /* Preserve original failures and every existing acceptance gate. */ }
      }
      if (!originalFailure && (failures.size || (!excluded && (!breakpointId || !verifiedDocuments())))) throw new Error('Original-case owner-isolation hydration diagnostic was unavailable')
    },
  }
}
