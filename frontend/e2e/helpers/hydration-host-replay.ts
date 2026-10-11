import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

export const NEXT_VERSION = '15.5.27'
export const REACT_VERSION = '19.2.0-canary-0bdb9206-20250818'
export const RENDERER_SHA256 = '9bcaacd92279559075407d2fb09b19893f03f9b93ad74eb0ef42b31b66f6053e'
export const RENDERER_BYTES = 530233
export const UPSTREAM_CURSOR_FIX = 'https://github.com/react/react/commit/c18662405'
export const REPLAY_ISSUE = 'https://github.com/react/react/issues/37584'
// Provenance from the original CI traces, not a fixture dependency or request.
export const ORIGINAL_CHUNK = {
  sha256: 'a0e4c895093e4f49edffedacbeca356d139ebced5a1f3b68cd5783f6a94388b3',
  bytes: 173025,
}
export const HOST_MARKUP = '<div id="outer"><p id="before">before</p><div id="target"><section id="child">lazy child</section></div><p id="after">after</p></div>'
export const HOST_IDS = ['outer', 'before', 'target', 'child', 'after'] as const

const helperAnchor = 'function upgradeHydrationErrorsToRecoverable() {'
const replayAnchor = '    case 5:\n      resetHooksOnUnwind(next);\n    default:\n      unwindInterruptedWork(current, next),'
// Faithful production-form translation of c18662405's helper and case-5 call.
// This deliberately retains the non-hydrating insertion branch and excludes
// HostSingleton/HostHoistable. It is never written into Next or node_modules.
export const CURSOR_HELPER = `function popHydrationStateOnInterruptedWork(fiber) {
  if (fiber !== hydrationParentFiber) return;
  if (!isHydrating) {
    popToNextHostParent(fiber);
    isHydrating = !0;
    return;
  }
  popToNextHostParent(fiber);
  if (5 === fiber.tag && null !== fiber.stateNode)
    nextHydratableInstance = fiber.stateNode;
}
`
const patchedReplayAnchor = replayAnchor.replace(
  '      resetHooksOnUnwind(next);',
  '      resetHooksOnUnwind(next);\n      popHydrationStateOnInterruptedWork(next);',
)

export function sha256(source: string | Buffer): string {
  return createHash('sha256').update(source).digest('hex')
}

function requireExactlyOnce(source: string, anchor: string): void {
  if (source.split(anchor).length !== 2) throw new Error('Expected one exact vendored hydration patch anchor')
}

export function assertRendererSource(source: string): void {
  if (Buffer.byteLength(source) !== RENDERER_BYTES || sha256(source) !== RENDERER_SHA256) {
    throw new Error('Next-vendored hydration renderer changed; review provenance and the exact backport before updating this test')
  }
  if (!source.includes(`exports.version = "${REACT_VERSION}";`)) throw new Error('Unexpected vendored ReactDOM version')
}

export function applyCursorBackport(source: string): string {
  assertRendererSource(source)
  requireExactlyOnce(source, helperAnchor)
  requireExactlyOnce(source, replayAnchor)
  if (source.includes('popHydrationStateOnInterruptedWork')) throw new Error('Vendored renderer already contains the cursor fix')
  const patched = source.replace(helperAnchor, CURSOR_HELPER + helperAnchor).replace(replayAnchor, patchedReplayAnchor)
  if (undoCursorBackport(patched) !== source) throw new Error('Hydration backport changed unrelated renderer code')
  return patched
}

export function undoCursorBackport(source: string): string {
  requireExactlyOnce(source, CURSOR_HELPER + helperAnchor)
  requireExactlyOnce(source, patchedReplayAnchor)
  return source.replace(CURSOR_HELPER + helperAnchor, helperAnchor).replace(patchedReplayAnchor, replayAnchor)
}

export function readVendoredRenderer(frontendRoot: string) {
  const requireFromFrontend = createRequire(path.join(frontendRoot, 'package.json'))
  const nextRoot = path.dirname(requireFromFrontend.resolve('next/package.json'))
  const nextVersion = JSON.parse(readFileSync(path.join(nextRoot, 'package.json'), 'utf8')).version
  if (nextVersion !== NEXT_VERSION) throw new Error(`Expected Next ${NEXT_VERSION}; got ${nextVersion}`)
  const rendererPath = path.join(nextRoot, 'dist/compiled/react-dom/cjs/react-dom-client.production.js')
  const source = readFileSync(rendererPath, 'utf8')
  assertRendererSource(source)
  const dependencies = {
    'next/dist/compiled/react': { relativePath: 'react/cjs/react.production.js', sha256: '125bcbc3a09182b916dce9d7e0d4b1b569f8e994f4bb98ae0d54855f9b74bfb7' },
    'next/dist/compiled/react-dom': { relativePath: 'react-dom/cjs/react-dom.production.js', sha256: '4204c2dc130ff27e7733de951bf64fe6acb0e8bcfa645a812958085d41829bf4' },
    'next/dist/compiled/scheduler': { relativePath: 'scheduler/cjs/scheduler.production.js', sha256: '679adff761d31e9426604f80c0e99be44a3e6f4c6834b0218ecf0312a67c171f' },
  }
  const alias: Record<string, string> = {}
  for (const [name, dependency] of Object.entries(dependencies)) {
    const dependencyPath = path.join(nextRoot, 'dist/compiled', dependency.relativePath)
    if (sha256(readFileSync(dependencyPath)) !== dependency.sha256) throw new Error(`Unexpected vendored dependency: ${name}`)
    alias[name] = dependencyPath
  }
  return { rendererPath, source, alias, nextVersion }
}

// Locations in the locally esbuild-bundled, unminified renderer. The baseline
// renderer source has no probes or behavioral edits. Identical CDP non-pausing
// logpoints observe both variants; no scheduler replacement or forced yield.
export function replayProbeLocations(bundle: string) {
  const locationAfter = (pattern: RegExp) => {
    const matches = [...bundle.matchAll(pattern)]
    if (matches.length !== 1 || matches[0].index === undefined) throw new Error('Expected one exact hydration observation location')
    const offset = matches[0].index + matches[0][0].length
    const lines = bundle.slice(0, offset).split('\n')
    return { lineNumber: lines.length - 1, columnNumber: lines[lines.length - 1].length }
  }
  return {
    replay: locationAfter(/function replaySuspendedUnitOfWork\(unitOfWork\) \{\s*/g),
    resolvedThenable: locationAfter(/case 7:\s*(?=isThenableResolved\(thrownValue\))/g),
  }
}

export function selectProbeBreakpoint(
  requested: { lineNumber: number; columnNumber: number },
  candidates: Array<{ scriptId: string; lineNumber: number; columnNumber?: number }>,
  scriptId: string,
) {
  const location = candidates
    .filter((candidate) => candidate.scriptId === scriptId && candidate.lineNumber === requested.lineNumber && (candidate.columnNumber ?? 0) >= requested.columnNumber)
    .sort((first, second) => (first.columnNumber ?? 0) - (second.columnNumber ?? 0))[0]
  if (!location) throw new Error('No executable hydration observation position on the verified statement line')
  return { scriptId, lineNumber: location.lineNumber, columnNumber: location.columnNumber ?? 0 }
}
