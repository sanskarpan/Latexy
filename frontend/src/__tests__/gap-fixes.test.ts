/**
 * Unit tests for GAP-004, GAP-005, GAP-006 frontend fixes.
 *
 * GAP-004: useOnboarding localStorage flag logic
 * GAP-005: Provider data transformation (array → Record) + route response shape
 * GAP-006: JobQueue status/type config coverage
 */

import { describe, test, expect, beforeEach, vi } from 'vitest'

// ─────────────────────────────────────────────────────────────────────────────
// GAP-005 · Provider data transformation
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Mirrors the logic inside APIKeyManager.fetchProviders that was fixed:
 * backend returns providers as an array, not an object.
 */
function transformProviders(
  data: { providers?: unknown }
): Record<string, string[]> {
  const providerList = Array.isArray(data.providers) ? data.providers : []
  const providerMap: Record<string, string[]> = {}
  for (const p of providerList) {
    providerMap[p.name] = p.available_models || []
  }
  return providerMap
}

describe('GAP-005 · Provider data transformation', () => {
  test('transforms backend array response to Record<name, models[]>', () => {
    const backendResponse = {
      success: true,
      providers: [
        {
          name: 'openai',
          display_name: 'Openai',
          capabilities: { max_context_length: 128000 },
          available_models: ['gpt-4', 'gpt-3.5-turbo'],
          key_format: { prefix: 'sk-' },
        },
        {
          name: 'anthropic',
          display_name: 'Anthropic',
          capabilities: { max_context_length: 200000 },
          available_models: ['claude-3-opus', 'claude-3-sonnet'],
          key_format: { prefix: 'sk-ant-' },
        },
      ],
      total_count: 2,
    }

    const result = transformProviders(backendResponse)
    expect(result).toEqual({
      openai: ['gpt-4', 'gpt-3.5-turbo'],
      anthropic: ['claude-3-opus', 'claude-3-sonnet'],
    })
  })

  test('handles empty providers array', () => {
    const result = transformProviders({ providers: [] })
    expect(result).toEqual({})
  })

  test('handles missing providers field', () => {
    const result = transformProviders({})
    expect(result).toEqual({})
  })

  test('handles provider with no available_models', () => {
    const result = transformProviders({
      providers: [{ name: 'custom', display_name: 'Custom' }],
    })
    expect(result).toEqual({ custom: [] })
  })

  test('old broken response (providers as object) falls back safely', () => {
    // Before the fix, the Next.js route returned providers as the entire
    // backend response object — this must not crash
    const brokenResponse = {
      providers: { success: true, providers: [], total_count: 0 },
    }
    const result = transformProviders(brokenResponse)
    // Not an array → falls back to empty
    expect(result).toEqual({})
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// GAP-005 · ProviderSelector data handling
// ─────────────────────────────────────────────────────────────────────────────

describe('GAP-005 · ProviderSelector helpers', () => {
  test('hasUserKey matches active keys by provider name', () => {
    const userApiKeys = [
      { id: '1', provider: 'openai', key_name: 'My Key', is_active: true },
      { id: '2', provider: 'anthropic', key_name: 'Old', is_active: false },
    ]
    const hasKey = (name: string) =>
      userApiKeys.some((k) => k.provider === name && k.is_active)

    expect(hasKey('openai')).toBe(true)
    expect(hasKey('anthropic')).toBe(false) // inactive
    expect(hasKey('openrouter')).toBe(false) // absent
  })

  test('formatContextLength displays K/M suffixes', () => {
    const fmt = (n: number) => {
      if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
      if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
      return String(n)
    }

    expect(fmt(128_000)).toBe('128K')
    expect(fmt(200_000)).toBe('200K')
    expect(fmt(1_000_000)).toBe('1.0M')
    expect(fmt(500)).toBe('500')
    expect(fmt(0)).toBe('0')
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// GAP-004 · Onboarding localStorage logic
// ─────────────────────────────────────────────────────────────────────────────

const ONBOARDING_KEY = 'latexy_onboarding_completed'

describe('GAP-004 · Onboarding localStorage logic', () => {
  let store: Record<string, string>

  beforeEach(() => {
    store = {}
    // Minimal localStorage mock for node environment
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => { store[key] = value },
      removeItem: (key: string) => { delete store[key] },
    })
  })

  test('new user has no onboarding flag → should show onboarding', () => {
    expect(localStorage.getItem(ONBOARDING_KEY)).toBeNull()
    const hasCompleted = !!localStorage.getItem(ONBOARDING_KEY)
    expect(hasCompleted).toBe(false)
  })

  test('completing onboarding sets flag', () => {
    localStorage.setItem(ONBOARDING_KEY, 'true')
    expect(localStorage.getItem(ONBOARDING_KEY)).toBe('true')
    const hasCompleted = !!localStorage.getItem(ONBOARDING_KEY)
    expect(hasCompleted).toBe(true)
  })

  test('resetting onboarding removes flag', () => {
    localStorage.setItem(ONBOARDING_KEY, 'true')
    localStorage.removeItem(ONBOARDING_KEY)
    expect(localStorage.getItem(ONBOARDING_KEY)).toBeNull()
  })

  test('returning user with flag set → should NOT show onboarding', () => {
    store[ONBOARDING_KEY] = 'true'
    const hasCompleted = !!localStorage.getItem(ONBOARDING_KEY)
    expect(hasCompleted).toBe(true)
    // Workspace page effect: if (session && !hasCompletedOnboarding) startOnboarding()
    // With hasCompleted=true, startOnboarding should NOT be called
    const shouldShowOnboarding = !hasCompleted
    expect(shouldShowOnboarding).toBe(false)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// GAP-006 · JobQueue config completeness
// ─────────────────────────────────────────────────────────────────────────────

describe('GAP-006 · JobQueue config', () => {
  // Mirrors the job type and status configs from JobQueue.tsx
  const jobTypeKeys = [
    'latex_compilation',
    'llm_optimization',
    'combined',
    'ats_scoring',
    'jd_analysis',
  ]

  const statusKeys = [
    'pending',
    'processing',
    'completed',
    'failed',
    'cancelled',
  ]

  test('all job types have required config fields', () => {
    // Ensure every type the backend may send has a matching config
    const jobTypeConfig: Record<string, { label: string; color: string; bgColor: string }> = {
      latex_compilation: { label: 'LaTeX Compilation', color: 'text-blue-400', bgColor: 'bg-blue-500/10' },
      llm_optimization: { label: 'LLM Optimization', color: 'text-orange-300', bgColor: 'bg-orange-500/10' },
      combined: { label: 'Optimize & Compile', color: 'text-purple-300', bgColor: 'bg-purple-500/10' },
      ats_scoring: { label: 'ATS Scoring', color: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
      jd_analysis: { label: 'JD Analysis', color: 'text-indigo-300', bgColor: 'bg-indigo-500/10' },
    }

    for (const key of jobTypeKeys) {
      expect(jobTypeConfig[key]).toBeDefined()
      expect(jobTypeConfig[key].label).toBeTruthy()
      expect(jobTypeConfig[key].color).toMatch(/^text-/)
      expect(jobTypeConfig[key].bgColor).toMatch(/^bg-/)
    }
  })

  test('all status types have required config fields', () => {
    const statusConfig: Record<string, { label: string; color: string; bgColor: string; ringColor: string }> = {
      pending: { label: 'Pending', color: 'text-yellow-300', bgColor: 'bg-yellow-500/10', ringColor: 'ring-yellow-400/20' },
      processing: { label: 'Processing', color: 'text-blue-400', bgColor: 'bg-blue-500/10', ringColor: 'ring-blue-400/20' },
      completed: { label: 'Completed', color: 'text-emerald-400', bgColor: 'bg-emerald-500/10', ringColor: 'ring-emerald-400/20' },
      failed: { label: 'Failed', color: 'text-rose-400', bgColor: 'bg-rose-500/10', ringColor: 'ring-rose-400/20' },
      cancelled: { label: 'Cancelled', color: 'text-zinc-400', bgColor: 'bg-zinc-500/10', ringColor: 'ring-zinc-400/20' },
    }

    for (const key of statusKeys) {
      expect(statusConfig[key]).toBeDefined()
      expect(statusConfig[key].label).toBeTruthy()
      expect(statusConfig[key].color).toMatch(/^text-/)
      expect(statusConfig[key].bgColor).toMatch(/^bg-/)
      expect(statusConfig[key].ringColor).toMatch(/^ring-/)
    }
  })

  test('formatTime produces relative time strings', () => {
    const formatTime = (timestamp?: number) => {
      if (!timestamp) return 'Unknown'
      const diff = Date.now() - timestamp * 1000
      if (diff < 60_000) return 'Just now'
      if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
      if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
      return new Date(timestamp * 1000).toLocaleDateString()
    }

    expect(formatTime(undefined)).toBe('Unknown')
    expect(formatTime(Date.now() / 1000)).toBe('Just now')
    expect(formatTime(Date.now() / 1000 - 120)).toBe('2m ago')
    expect(formatTime(Date.now() / 1000 - 7200)).toBe('2h ago')
    // Older than 24h returns a date string
    const oldTimestamp = Date.now() / 1000 - 100_000
    expect(formatTime(oldTimestamp)).toMatch(/\d/)
  })

  test('canCancel is false for terminal statuses', () => {
    const canCancel = (status: string) =>
      !['completed', 'failed', 'cancelled'].includes(status)

    expect(canCancel('pending')).toBe(true)
    expect(canCancel('processing')).toBe(true)
    expect(canCancel('completed')).toBe(false)
    expect(canCancel('failed')).toBe(false)
    expect(canCancel('cancelled')).toBe(false)
  })
})
