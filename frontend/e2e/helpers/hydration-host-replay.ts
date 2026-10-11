import { readFileSync } from 'node:fs'
import path from 'node:path'

import {
  NEXT_VERSION, PRODUCTION_RENDERER, assertRendererSource, sha256,
  undoCursorBackport, verifyNextHydrationBackport,
} from '../../scripts/next-hydration-backport.mjs'

export {
  NEXT_VERSION, REACT_VERSION, RENDERER_SHA256, RENDERER_BYTES,
  PATCHED_RENDERER_SHA256, PATCHED_RENDERER_BYTES, UPSTREAM_CURSOR_FIX,
  CURSOR_HELPER, INTEGRITY, applyCursorBackport, undoCursorBackport,
  assertRendererSource, sha256, verifyNextHydrationBackport,
} from '../../scripts/next-hydration-backport.mjs'
export const REPLAY_ISSUE = 'https://github.com/react/react/issues/37584'
// Historical provenance from the original failed CI, not the current runtime.
export const ORIGINAL_CHUNK = {
  sha256: 'a0e4c895093e4f49edffedacbeca356d139ebced5a1f3b68cd5783f6a94388b3',
  bytes: 173025,
}
export const HOST_MARKUP = '<div id="outer"><p id="before">before</p><div id="target"><section id="child">lazy child</section></div><p id="after">after</p></div>'
export const HOST_IDS = ['outer', 'before', 'target', 'child', 'after'] as const

export function readVendoredRenderer(frontendRoot: string) {
  const { nextRoot, nextVersion } = verifyNextHydrationBackport(frontendRoot)
  if (nextVersion !== NEXT_VERSION) throw new Error('Unexpected Next version')
  const rendererPath = path.join(nextRoot, 'dist/compiled/react-dom/cjs', PRODUCTION_RENDERER)
  const source = readFileSync(rendererPath, 'utf8')
  assertRendererSource(source, PRODUCTION_RENDERER, 'patched')
  // The red arm is the byte-identical original, reconstructed by exact inverse.
  // The green arm imports rendererPath, the actual effective installed runtime.
  const originalSource = undoCursorBackport(source)
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
  return { rendererPath, source, originalSource, alias, nextVersion }
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
