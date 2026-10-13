import { createHash } from 'node:crypto'
import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { verifyMonacoCancellationBackport } from './monaco-cancellation-backport.mjs'

const require = createRequire(import.meta.url)
const scriptPath = fileURLToPath(import.meta.url)
const frontendDir = path.resolve(path.dirname(scriptPath), '..')

// Include relative names and full bytes in sorted order. Package version alone
// cannot invalidate a previously generated same-version, unpatched AMD bundle.
export async function fingerprintMonacoAssets(directory) {
  const hash = createHash('sha256')
  async function visit(relativePath) {
    const entries = await readdir(path.join(directory, relativePath), { withFileTypes: true })
    entries.sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0)
    for (const entry of entries) {
      const relative = path.posix.join(relativePath, entry.name)
      if (entry.isDirectory()) await visit(relative)
      else if (entry.isFile()) {
        const contents = await readFile(path.join(directory, relative))
        hash.update(`${relative}\0${contents.length}\0`).update(contents)
      } else throw new Error(`Unsupported Monaco asset entry: ${relative}`)
    }
  }
  await visit('')
  return hash.digest('hex')
}

export async function prepareMonaco({
  monacoRoot = path.dirname(require.resolve('monaco-editor/package.json')),
  outputRoot = path.join(frontendDir, 'public', 'monaco'),
} = {}) {
  const version = verifyMonacoCancellationBackport(monacoRoot)
  const sourceDir = path.join(monacoRoot, 'min', 'vs')
  const outputDir = path.join(outputRoot, 'vs')
  const versionFile = path.join(outputRoot, '.version')
  const fingerprint = await fingerprintMonacoAssets(sourceDir)
  const identity = `${version}:${fingerprint}`
  let preparedIdentity = ''
  let outputFingerprint = ''
  try {
    preparedIdentity = (await readFile(versionFile, 'utf8')).trim()
    outputFingerprint = await fingerprintMonacoAssets(outputDir)
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
    // First preparation, legacy output, or an incomplete prior copy.
  }
  if (preparedIdentity === identity && outputFingerprint === fingerprint) return false
  await rm(outputDir, { recursive: true, force: true })
  await mkdir(outputRoot, { recursive: true })
  await cp(sourceDir, outputDir, { recursive: true })
  if (await fingerprintMonacoAssets(outputDir) !== fingerprint) {
    throw new Error('Prepared Monaco assets do not match the installed distribution')
  }
  await writeFile(versionFile, `${identity}\n`)
  return true
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) await prepareMonaco()
