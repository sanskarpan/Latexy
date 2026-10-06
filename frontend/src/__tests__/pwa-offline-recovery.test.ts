import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const CONFIG = readFileSync(new URL('../../next.config.js', import.meta.url), 'utf8')

describe('PWA offline recovery', () => {
  it('does not reload the page before owner-scoped reconnect work completes', () => {
    expect(CONFIG).toContain('reloadOnOnline: false')
    expect(CONFIG).toContain('location.reload() unconditionally')
  })
})
