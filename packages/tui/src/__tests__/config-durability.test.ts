/**
 * Config durability.
 *
 * writeFile() truncates before writing, so an interruption left a half-written
 * config that would not parse — and readDiskConfig() swallowed the failure and
 * returned defaults, which presents to the user as being mysteriously logged out.
 */
import { mkdtemp, readFile, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let dir = ''
const ORIGINAL_XDG = process.env['XDG_CONFIG_HOME']

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'latexy-cfg-'))
  process.env['XDG_CONFIG_HOME'] = dir
  vi.resetModules()
})

afterEach(() => {
  if (ORIGINAL_XDG === undefined) delete process.env['XDG_CONFIG_HOME']
  else process.env['XDG_CONFIG_HOME'] = ORIGINAL_XDG
})

async function fresh() {
  return import('../lib/config.js')
}

describe('config durability', () => {
  it('round-trips a token', async () => {
    const { writeConfig, readConfig } = await fresh()
    await writeConfig({ token: 'abc123', email: 'a@b.c' })
    delete process.env['LATEXY_SESSION_TOKEN']
    const cfg = await readConfig()
    expect(cfg.token).toBe('abc123')
    expect(cfg.email).toBe('a@b.c')
  })

  it('writes the token file 0600', async () => {
    const { writeConfig } = await fresh()
    await writeConfig({ token: 'secret' })
    const st = await stat(join(dir, 'latexy', 'config.toml'))
    expect(st.mode & 0o777).toBe(0o600)
  })

  it('creates the config directory 0700, not world-traversable', async () => {
    const { writeConfig } = await fresh()
    await writeConfig({ token: 'secret' })
    const st = await stat(join(dir, 'latexy'))
    expect(st.mode & 0o077, 'directory is readable/traversable by others').toBe(0)
  })

  it('leaves no temp file behind after a successful write', async () => {
    const { writeConfig } = await fresh()
    await writeConfig({ token: 'secret' })
    const { readdir } = await import('node:fs/promises')
    const entries = await readdir(join(dir, 'latexy'))
    expect(entries.filter(e => e.includes('.tmp'))).toEqual([])
  })

  it('does not destroy an unparseable config on read', async () => {
    // The old behaviour silently fell back to defaults; the file itself must at
    // least survive so the user can recover whatever was in it.
    const { mkdir } = await import('node:fs/promises')
    await mkdir(join(dir, 'latexy'), { recursive: true })
    const path = join(dir, 'latexy', 'config.toml')
    await writeFile(path, 'this is not = valid toml [[[')

    const { readConfig } = await fresh()
    delete process.env['LATEXY_SESSION_TOKEN']
    const cfg = await readConfig()
    expect(cfg.token).toBeNull()                       // degraded, as before
    expect(await readFile(path, 'utf-8')).toContain('not = valid')   // but not clobbered
  })

  it('an absent config is not an error', async () => {
    const { readConfig } = await fresh()
    delete process.env['LATEXY_SESSION_TOKEN']
    const cfg = await readConfig()
    expect(cfg.token).toBeNull()
  })
})
