import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(scriptDir, '..')
const monacoPackagePath = require.resolve('monaco-editor/package.json')
const monacoPackage = require(monacoPackagePath)
const sourceDir = path.join(path.dirname(monacoPackagePath), 'min', 'vs')
const outputRoot = path.join(frontendDir, 'public', 'monaco')
const outputDir = path.join(outputRoot, 'vs')
const versionFile = path.join(outputRoot, '.version')

let preparedVersion = ''
try {
  preparedVersion = (await readFile(versionFile, 'utf8')).trim()
} catch {
  // First install/build: the generated assets do not exist yet.
}

if (preparedVersion !== monacoPackage.version) {
  await rm(outputDir, { recursive: true, force: true })
  await mkdir(outputRoot, { recursive: true })
  await cp(sourceDir, outputDir, { recursive: true })
  await writeFile(versionFile, `${monacoPackage.version}\n`)
}
