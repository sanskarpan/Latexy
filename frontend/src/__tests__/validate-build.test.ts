import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, it } from 'vitest'

const FRONTEND_ROOT = resolve(fileURLToPath(new URL('../..', import.meta.url)))
const VALIDATOR = join(FRONTEND_ROOT, 'scripts', 'validate-build.mjs')
const temporaryDistDirectories: string[] = []

afterEach(() => {
  for (const directory of temporaryDistDirectories.splice(0)) {
    rmSync(directory, { force: true, recursive: true })
  }
})

describe('production build artifact validation', () => {
  it('validates artifacts from NEXT_DIST_DIR instead of stale .next output', () => {
    const distDirectory = mkdtempSync(join(FRONTEND_ROOT, '.validate-build-test-'))
    temporaryDistDirectories.push(distDirectory)

    for (const relativePath of [
      'BUILD_ID',
      'build-manifest.json',
      'prerender-manifest.json',
      'routes-manifest.json',
      'server/app-paths-manifest.json',
      'standalone/server.js',
    ]) {
      const artifactPath = join(distDirectory, relativePath)
      mkdirSync(resolve(artifactPath, '..'), { recursive: true })
      writeFileSync(artifactPath, 'test artifact')
    }

    const output = execFileSync(process.execPath, [VALIDATOR, 'artifacts'], {
      cwd: FRONTEND_ROOT,
      encoding: 'utf8',
      env: {
        ...process.env,
        NEXT_DIST_DIR: basename(distDirectory),
      },
    })

    expect(output).toContain(`Frontend build artifacts validated in ${distDirectory}.`)
  })
})
