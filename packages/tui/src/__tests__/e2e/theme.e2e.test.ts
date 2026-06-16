import { describe, it, expect } from 'vitest'
import { theme } from '../../lib/theme.js'

describe('theme design tokens', () => {
  it('has brand color', () => {
    expect(typeof theme.brand).toBe('string')
  })

  it('has all health status colors', () => {
    expect(theme.health.healthy).toBeDefined()
    expect(theme.health.degraded).toBeDefined()
    expect(theme.health.unhealthy).toBeDefined()
    expect(theme.health.unknown).toBeDefined()
  })

  it('has all plan badge colors', () => {
    expect(theme.plan.free).toBeDefined()
    expect(theme.plan.basic).toBeDefined()
    expect(theme.plan.pro).toBeDefined()
    expect(theme.plan.byok).toBeDefined()
    expect(theme.plan.team).toBeDefined()
  })

  it('has error and success colors', () => {
    expect(theme.error).toBeDefined()
    expect(theme.success).toBeDefined()
  })
})
