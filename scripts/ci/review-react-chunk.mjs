// Reproducible review helper for the BUG-08 React runtime chunk pin.
// The gate only accepts exact reviewed byte-sets; this script never edits a pin.
//
// Usage:
//   node scripts/ci/review-react-chunk.mjs <candidate.js>
//     [--canonical <reference.js>]
//     [--expect-sha256 <hex>]
//     [--expect-bytes <integer>]
//     [--expect-implementation-sha256 <hex>]
//
// The review criterion is that the complete implementation suffix (everything
// from the first `function ` marker) is byte-identical to the canonical
// reviewed bundle. Only the webpack header IDs before that marker may differ.
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { basename } from 'node:path'

const ANCHOR = 'function rD(e){var n=Error(i(418,'
const IMPLEMENTATION_MARKER = 'function '
const CLAIM_PREFIX = 'function rD(e){'
const CLAIM_SUFFIX = 'var n='

function usage() {
  console.error('usage: node scripts/ci/review-react-chunk.mjs <candidate.js> [--canonical <reference.js>] [--expect-sha256 <hex>] [--expect-bytes <n>] [--expect-implementation-sha256 <hex>]')
}

function parseArgs(argv) {
  const options = { candidate: null, canonical: null, expectedSha256: null, expectedBytes: null, expectedImplementationSha256: null }
  for (let index = 0; index < argv.length; index++) {
    const argument = argv[index]
    if (argument === '--help' || argument === '-h') return { help: true }
    if (argument === '--canonical') options.canonical = argv[++index]
    else if (argument === '--expect-sha256') options.expectedSha256 = argv[++index]
    else if (argument === '--expect-bytes') options.expectedBytes = argv[++index]
    else if (argument === '--expect-implementation-sha256') options.expectedImplementationSha256 = argv[++index]
    else if (argument.startsWith('--')) throw new Error(`unknown option: ${argument}`)
    else if (!options.candidate) options.candidate = argument
    else throw new Error(`unexpected argument: ${argument}`)
  }
  if (!options.candidate) throw new Error('candidate chunk is required')
  return options
}

function review(path) {
  const bytes = readFileSync(path)
  let source
  try {
    source = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    throw new Error(`${path}: not valid UTF-8`)
  }
  const implementationIndex = source.indexOf(IMPLEMENTATION_MARKER)
  if (implementationIndex < 0) throw new Error(`${path}: implementation marker not found`)
  const claimIndex = source.indexOf(ANCHOR)
  if (claimIndex < 0) throw new Error(`${path}: reviewed rD anchor not found`)
  const header = source.slice(0, implementationIndex)
  const implementation = source.slice(implementationIndex)
  return {
    file: basename(path),
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    header,
    headerBytes: Buffer.byteLength(header),
    implementationBytes: Buffer.byteLength(implementation),
    implementationSha256: createHash('sha256').update(Buffer.from(implementation, 'utf8')).digest('hex'),
    claimColumn: claimIndex + CLAIM_PREFIX.length,
    lastColumn: claimIndex + CLAIM_PREFIX.length + CLAIM_SUFFIX.length,
    implementation,
  }
}

function normalizeHex(value) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/i.test(value)) throw new Error('expected a 64-character SHA-256 hex digest')
  return value.toLowerCase()
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.help) { usage(); return }
  const candidate = review(options.candidate)
  const checks = []
  const check = (name, expected, actual) => checks.push({ name, expected, actual, ok: expected === actual })

  if (options.expectedSha256 !== null) check('sha256', normalizeHex(options.expectedSha256), candidate.sha256)
  if (options.expectedBytes !== null) {
    if (!/^[0-9]+$/.test(options.expectedBytes)) throw new Error('--expect-bytes must be a non-negative integer')
    check('bytes', Number(options.expectedBytes), candidate.bytes)
  }
  if (options.expectedImplementationSha256 !== null) {
    check('implementation_sha256', normalizeHex(options.expectedImplementationSha256), candidate.implementationSha256)
  }

  let reference = null
  if (options.canonical) {
    reference = review(options.canonical)
    check('implementation_matches_canonical', true, reference.implementation === candidate.implementation)
    check('implementation_sha256_matches_canonical', reference.implementationSha256, candidate.implementationSha256)
  }

  const ok = checks.every((entry) => entry.ok)
  console.log(JSON.stringify({
    ok,
    candidate: {
      file: candidate.file,
      bytes: candidate.bytes,
      sha256: candidate.sha256,
      headerBytes: candidate.headerBytes,
      implementationBytes: candidate.implementationBytes,
      implementationSha256: candidate.implementationSha256,
      claimColumn: candidate.claimColumn,
      lastColumn: candidate.lastColumn,
      header: candidate.header,
    },
    canonical: reference ? {
      file: reference.file,
      bytes: reference.bytes,
      sha256: reference.sha256,
      headerBytes: reference.headerBytes,
      implementationBytes: reference.implementationBytes,
      implementationSha256: reference.implementationSha256,
      claimColumn: reference.claimColumn,
      lastColumn: reference.lastColumn,
      header: reference.header,
    } : null,
    checks,
  }, null, 2))
  if (!ok) process.exitCode = 1
}

try { main() } catch (error) {
  console.error(`review-react-chunk: ${error instanceof Error ? error.message : String(error)}`)
  usage()
  process.exitCode = 2
}
