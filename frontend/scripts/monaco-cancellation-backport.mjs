import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const MONACO_BACKPORT = JSON.parse(readFileSync(
  fileURLToPath(new URL('./monaco-cancellation-backport-integrity.json', import.meta.url)), 'utf8',
))

export function sha256(source) {
  return createHash('sha256').update(source).digest('hex')
}

// Installation belongs to pnpm's exact-version patch. This guard never edits
// installed dependencies or accepts a different runtime as equivalent.
export function verifyMonacoCancellationBackport(monacoRoot) {
  const { version } = JSON.parse(readFileSync(path.join(monacoRoot, 'package.json'), 'utf8'))
  if (version !== MONACO_BACKPORT.version) throw new Error(`Unsupported Monaco backport version: ${version}`)
  for (const [relativePath, integrity] of Object.entries(MONACO_BACKPORT.files)) {
    const source = readFileSync(path.join(monacoRoot, relativePath))
    if (sha256(source) !== integrity.patched) {
      throw new Error(`Monaco cancellation backport missing or changed: ${relativePath}`)
    }
  }
  return version
}
