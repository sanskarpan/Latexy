// Narrow MIT-licensed React backport, not a renderer/channel upgrade.
// https://github.com/react/react/commit/c18662405cc436646411647f8a8965c1c0594c3c
// https://github.com/react/react/pull/35494
// The four renderer license headers and compiled/react-dom/LICENSE stay intact.
import { createHash } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const NEXT_VERSION = '15.5.27'
export const REACT_VERSION = '19.2.0-canary-0bdb9206-20250818'
export const PRODUCTION_RENDERER = 'react-dom-client.production.js'
export const UPSTREAM_CURSOR_FIX = 'https://github.com/react/react/commit/c18662405cc436646411647f8a8965c1c0594c3c'
export const INTEGRITY = JSON.parse(readFileSync(new URL('./next-hydration-backport-integrity.json', import.meta.url), 'utf8'))
export const RENDERER_SHA256 = INTEGRITY.renderers[PRODUCTION_RENDERER].original.sha256
export const RENDERER_BYTES = INTEGRITY.renderers[PRODUCTION_RENDERER].original.bytes
export const PATCHED_RENDERER_SHA256 = INTEGRITY.renderers[PRODUCTION_RENDERER].patched.sha256
export const PATCHED_RENDERER_BYTES = INTEGRITY.renderers[PRODUCTION_RENDERER].patched.bytes

// Faithful production-form translation of the upstream hydration helper.
// supportsHydration is a compile-time true constant for these DOM renderers.
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

export function sha256(source) {
  return createHash('sha256').update(source).digest('hex')
}

function anchors(filename) {
  if (!Object.hasOwn(INTEGRITY.renderers, filename)) throw new Error('Unexpected renderer channel or filename')
  const development = filename.endsWith('.development.js')
  const indent = development ? '    ' : ''
  const fiber = development ? 'unitOfWork' : 'next'
  const helperAnchor = `${indent}function upgradeHydrationErrorsToRecoverable() {`
  const helper = CURSOR_HELPER.split('\n').filter(Boolean).map((line) => `${indent}${line}\n`).join('')
  const reset = `      resetHooksOnUnwind(${fiber});`
  const replayAnchor = `${indent}    case 5:\n${indent}${reset}\n${indent}    default:\n${indent}      unwindInterruptedWork(current, ${fiber}),`
  const patchedReplayAnchor = replayAnchor.replace(reset, `${reset}\n${indent}      popHydrationStateOnInterruptedWork(${fiber});`)
  return { helperAnchor, helper, replayAnchor, patchedReplayAnchor }
}

function requireExactlyOnce(source, anchor) {
  if (source.split(anchor).length !== 2) throw new Error('Expected one exact vendored hydration patch anchor')
}

export function assertRendererSource(source, filename = PRODUCTION_RENDERER, state = 'original') {
  anchors(filename)
  if (state !== 'original' && state !== 'patched') throw new Error('Unexpected renderer integrity state')
  const expected = INTEGRITY.renderers[filename][state]
  if (Buffer.byteLength(source) !== expected.bytes || sha256(source) !== expected.sha256) {
    throw new Error(`Next-vendored hydration renderer changed (${filename}, ${state}); review the exact backport before updating integrity`)
  }
  if (!source.includes(`exports.version = "${REACT_VERSION}";`)) throw new Error('Unexpected vendored ReactDOM version')
}

// These pure string operations are for inverse-baseline tests and review only.
// Installation is owned by pnpm's exact-version patch; the guard never writes.
export function applyCursorBackport(source, filename = PRODUCTION_RENDERER) {
  assertRendererSource(source, filename, 'original')
  const { helperAnchor, helper, replayAnchor, patchedReplayAnchor } = anchors(filename)
  requireExactlyOnce(source, helperAnchor)
  requireExactlyOnce(source, replayAnchor)
  if (source.includes('popHydrationStateOnInterruptedWork')) throw new Error('Vendored renderer already contains the cursor fix')
  const patched = source.replace(helperAnchor, helper + helperAnchor).replace(replayAnchor, patchedReplayAnchor)
  assertRendererSource(patched, filename, 'patched')
  if (undoCursorBackport(patched, filename) !== source) throw new Error('Hydration backport changed unrelated renderer code')
  return patched
}

export function undoCursorBackport(source, filename = PRODUCTION_RENDERER) {
  assertRendererSource(source, filename, 'patched')
  const { helperAnchor, helper, replayAnchor, patchedReplayAnchor } = anchors(filename)
  requireExactlyOnce(source, helper + helperAnchor)
  requireExactlyOnce(source, patchedReplayAnchor)
  const original = source.replace(helper + helperAnchor, helperAnchor).replace(patchedReplayAnchor, replayAnchor)
  assertRendererSource(original, filename, 'original')
  return original
}

function companionDigest(directory, omitted = new Set()) {
  const files = []
  const walk = (relative = '') => {
    for (const entry of readdirSync(path.join(directory, relative), { withFileTypes: true })) {
      const name = relative ? `${relative}/${entry.name}` : entry.name
      if (entry.isDirectory()) walk(name)
      else if (entry.isFile()) files.push(name)
      else throw new Error(`Unexpected vendored companion entry: ${name}`)
    }
  }
  walk()
  const digest = createHash('sha256')
  for (const name of files.sort()) {
    if (!omitted.has(name)) digest.update(`${name}\0${sha256(readFileSync(path.join(directory, name)))}\n`)
  }
  return digest.digest('hex')
}

export function verifyNextHydrationBackport(frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), config = {}) {
  const requireFromFrontend = createRequire(path.join(frontendRoot, 'package.json'))
  const nextRoot = path.dirname(requireFromFrontend.resolve('next/package.json'))
  const nextVersion = JSON.parse(readFileSync(path.join(nextRoot, 'package.json'), 'utf8')).version
  if (nextVersion !== NEXT_VERSION) throw new Error(`Expected exact Next ${NEXT_VERSION}; got ${nextVersion}`)
  // Use the pinned framework's own predicate, including future truthy options.
  const { needsExperimentalReact } = requireFromFrontend(path.join(nextRoot, 'dist/lib/needs-experimental-react.js'))
  if (process.env.__NEXT_EXPERIMENTAL_REACT || needsExperimentalReact(config)) throw new Error('Unexpected experimental React channel; normal-channel backport is not applicable')
  for (const filename of Object.keys(INTEGRITY.renderers)) {
    const source = readFileSync(path.join(nextRoot, 'dist/compiled/react-dom/cjs', filename), 'utf8')
    assertRendererSource(source, filename, 'patched')
    // Validates the full preimage too, so unrelated edits cannot hide in a patch.
    undoCursorBackport(source, filename)
  }
  for (const [name, expected] of Object.entries(INTEGRITY.companions)) {
    const omitted = name === 'react-dom' ? new Set(Object.keys(INTEGRITY.renderers).map((file) => `cjs/${file}`)) : new Set()
    if (companionDigest(path.join(nextRoot, 'dist/compiled', name), omitted) !== expected) {
      throw new Error(`Next-vendored matched companion changed: ${name}`)
    }
  }
  return { nextRoot, nextVersion }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  verifyNextHydrationBackport()
  console.log(`Next ${NEXT_VERSION} normal-channel hydration backport and matched companions verified.`)
}
