// Retain unmodified public build bytes for explicit diagnostic-pin review.
// This evidence collector never chooses a test variant or changes an allowlist.
import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const chunks = join(process.cwd(), '.next', 'static', 'chunks')
const anchor = 'function rD(e){var n=Error(i(418,'
const candidates = readdirSync(chunks).filter(name => name.endsWith('.js')).flatMap(name => {
  const bytes = readFileSync(join(chunks, name))
  const source = bytes.toString('utf8')
  return bytes.length >= 150_000 && bytes.length <= 200_000 && source.includes(anchor)
    ? [{ name, bytes, source }] : []
})
if (candidates.length !== 1) throw new Error('Expected exactly one React diagnostic bundle candidate')
const { name, bytes, source } = candidates[0]
const hash = value => createHash('sha256').update(value).digest('hex')
const claimColumn = source.indexOf(anchor) + 'function rD(e){'.length
const output = join(process.cwd(), 'test-results', 'hydration-bundle-review')
mkdirSync(output, { recursive: true })
copyFileSync(join(chunks, name), join(output, name))
const descriptor = {
  chunk: `/_next/static/chunks/${name}`,
  sha256: hash(bytes),
  bytes: bytes.length,
  claimColumn,
  lastColumn: claimColumn + 'var n='.length,
  implementation_sha256: hash(source.slice(source.indexOf('function '))),
  scope: 'Unmodified public bundle candidate; requires independent review before pinning',
}
writeFileSync(join(output, 'descriptor.json'), `${JSON.stringify(descriptor, null, 2)}\n`)
console.log(JSON.stringify(descriptor))
