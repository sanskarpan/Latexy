import { readFileSync } from 'node:fs'
import { describe, expect, it, vi } from 'vitest'
import {
  LINTER_DEDUPE_WINDOW_MS,
  LINTER_SAMPLE_STORAGE_KEY,
  buildLinterTelemetryEvents,
  createLinterTelemetryClient,
  sanitizeLinterRoute,
} from '@/lib/linter-telemetry'

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial))
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    removeItem: (key: string) => {
      values.delete(key)
    },
    setItem: (key: string, value: string) => {
      values.set(key, value)
    },
  } as Storage
}

function client({
  consent = 'granted' as 'granted' | 'denied' | null,
  sampleBucket = 1,
  now = 1_000,
} = {}) {
  const send = vi.fn()
  const telemetry = createLinterTelemetryClient({
    readConsent: () => consent,
    getStorage: () => memoryStorage({ [LINTER_SAMPLE_STORAGE_KEY]: String(sampleBucket) }),
    now: () => now,
    random: () => 0,
    send,
  })
  return { telemetry, send }
}

const ISSUES = [
  { ruleId: 'deprecated-bf', severity: 'warning' },
  { ruleId: 'deprecated-bf', severity: 'warning' },
  { ruleId: 'wrong-quotes', severity: 'info' },
]

describe('linter telemetry privacy boundary', () => {
  it('emits only allowlisted keys and never issue text or positions', () => {
    const events = buildLinterTelemetryEvents(
      [
        {
          ruleId: 'deprecated-bf',
          severity: 'warning',
          line: 42,
          column: 7,
          message: 'secret line content',
          fixable: true,
        } as never,
        { ruleId: 'not-a-rule', severity: 'warning' },
        { ruleId: 'wrong-quotes', severity: 'nope' },
      ],
      { fixed: false, route: '/workspace/private-resume-2148/edit?token=secret' },
    )

    expect(events).toEqual([
      {
        rule_id: 'deprecated-bf',
        severity: 'warning',
        route: '/workspace/:resumeId/edit',
        fixed: false,
        issue_count: 1,
      },
    ])
    expect(Object.keys(events[0])).toEqual([
      'rule_id',
      'severity',
      'route',
      'fixed',
      'issue_count',
    ])
    expect(JSON.stringify(events)).not.toContain('secret')
    expect(JSON.stringify(events)).not.toContain('private-resume-2148')
  })

  it('buckets dynamic paths into a fixed route vocabulary', () => {
    expect(sanitizeLinterRoute('/workspace/abc-123/edit')).toBe('/workspace/:resumeId/edit')
    expect(sanitizeLinterRoute('/workspaces/team-1/recruiter')).toBe(
      '/workspaces/:workspaceId/recruiter',
    )
    expect(sanitizeLinterRoute('/try?token=share-secret')).toBe('/try')
    expect(sanitizeLinterRoute('/workspace/private-id/some-unknown-panel')).toBe('/other')
    expect(sanitizeLinterRoute('https://evil.example/workspace/id/edit')).toBe('/other')
  })

  it('groups issues by rule and severity, preserving counts only', () => {
    const events = buildLinterTelemetryEvents(ISSUES, {
      fixed: true,
      route: '/workspace/:resumeId/edit',
    })
    expect(events).toEqual([
      {
        rule_id: 'deprecated-bf',
        severity: 'warning',
        route: '/workspace/:resumeId/edit',
        fixed: true,
        issue_count: 2,
      },
      {
        rule_id: 'wrong-quotes',
        severity: 'info',
        route: '/workspace/:resumeId/edit',
        fixed: true,
        issue_count: 1,
      },
    ])
  })
})

describe('linter telemetry consent, sampling and dedupe', () => {
  it('sends nothing without analytics consent', () => {
    const { telemetry, send } = client({ consent: 'denied' })
    expect(telemetry.report(ISSUES, { fixed: false })).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('samples sessions deterministically, so a non-sampled session stays quiet', () => {
    const sampled = client({ sampleBucket: 1 })
    expect(sampled.telemetry.report(ISSUES, { fixed: false })).toBe(true)
    expect(sampled.send).toHaveBeenCalledTimes(1)

    const notSampled = client({ sampleBucket: 100 })
    expect(notSampled.telemetry.report(ISSUES, { fixed: false })).toBe(false)
    expect(notSampled.send).not.toHaveBeenCalled()
  })

  it('deduplicates an identical repeated lint run inside the rolling window', () => {
    let now = 1_000
    const send = vi.fn()
    const telemetry = createLinterTelemetryClient({
      readConsent: () => 'granted',
      getStorage: () => memoryStorage({ [LINTER_SAMPLE_STORAGE_KEY]: '1' }),
      now: () => now,
      random: () => 0,
      send,
    })

    expect(telemetry.report(ISSUES, { fixed: false })).toBe(true)
    expect(telemetry.report(ISSUES, { fixed: false })).toBe(false)
    expect(send).toHaveBeenCalledTimes(1)

    // A changed issue count is a new observation.
    now += 1
    expect(
      telemetry.report([...ISSUES, { ruleId: 'deprecated-bf', severity: 'warning' }], {
        fixed: false,
      }),
    ).toBe(true)
    expect(send).toHaveBeenCalledTimes(2)

    now += LINTER_DEDUPE_WINDOW_MS
    expect(telemetry.report(ISSUES, { fixed: false })).toBe(true)
    expect(send).toHaveBeenCalledTimes(3)
  })

  it('keeps fix/applied events on the same allowlisted payload', () => {
    const { telemetry, send } = client()
    expect(telemetry.report([{ ruleId: 'missing-label', severity: 'info' }], { fixed: true })).toBe(
      true,
    )
    expect(send).toHaveBeenCalledWith([
      {
        rule_id: 'missing-label',
        severity: 'info',
        route: '/other',
        fixed: true,
        issue_count: 1,
      },
    ])
  })

  it('reads the shared analytics consent gate and uses first-party error handling', () => {
    const source = readFileSync(new URL('../lib/linter-telemetry.ts', import.meta.url), 'utf8')
    const hook = readFileSync(new URL('../hooks/useLatexLinter.ts', import.meta.url), 'utf8')
    const page = readFileSync(
      new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url),
      'utf8',
    )

    expect(source).toContain('readAnalyticsConsent')
    expect(source).toContain("readConsent() !== 'granted'")
    expect(source).toContain('/telemetry/linter')
    expect(source).toContain('LINTER_SAMPLE_RATE_PERCENT = 25')
    expect(source).toContain('LINTER_DEDUPE_WINDOW_MS')
    expect(hook).toContain("reportLinterIssues(nextIssues, { fixed: false })")
    expect(page).toContain('reportLinterIssues(fixableIssues, { fixed: true })')
    expect(page).toContain('reportLinterIssues([issue], { fixed: true })')
  })
})
