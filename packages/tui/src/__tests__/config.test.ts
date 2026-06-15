import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const TMP_CONFIG = join(tmpdir(), `latexy-test-${process.pid}`)

describe('config', () => {
  beforeEach(() => {
    process.env['XDG_CONFIG_HOME'] = TMP_CONFIG
    mkdirSync(join(TMP_CONFIG, 'latexy'), { recursive: true })
    vi.resetModules()
  })

  afterEach(() => {
    rmSync(TMP_CONFIG, { recursive: true, force: true })
    delete process.env['XDG_CONFIG_HOME']
  })

  it('returns defaults when config file missing', async () => {
    const { readConfig } = await import('../lib/config.js')
    const cfg = await readConfig()
    expect(cfg.backendUrl).toBe('http://localhost:8030')
    expect(cfg.token).toBeNull()
  })

  it('round-trips token write + read', async () => {
    const { readConfig, writeConfig } = await import('../lib/config.js')
    await writeConfig({ token: 'tok123', email: 'a@b.com' })
    const cfg = await readConfig()
    expect(cfg.token).toBe('tok123')
    expect(cfg.email).toBe('a@b.com')
  })

  it('clearConfig removes token and email', async () => {
    const { readConfig, writeConfig, clearConfig } = await import('../lib/config.js')
    await writeConfig({ token: 'tok', email: 'x@y.com' })
    await clearConfig()
    const cfg = await readConfig()
    expect(cfg.token).toBeNull()
    expect(cfg.email).toBeNull()
  })
})
