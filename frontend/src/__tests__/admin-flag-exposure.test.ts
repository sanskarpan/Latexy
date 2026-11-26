import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  OPERATIONAL_FLAG_KEYS,
  buildFlagExposurePayload,
  type FlagExposureMap,
} from '@/lib/analytics/flag-exposure'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('flag exposure payload boundary', () => {
  it('sends only operational flag keys and the evaluated boolean', () => {
    const payload = buildFlagExposurePayload(
      { upgrade_ctas: true, billing: false, deep_analysis_trial: true },
      '550e8400-e29b-41d4-a716-446655440000',
    )

    expect(payload).toEqual({
      anonymous_id: '550e8400-e29b-41d4-a716-446655440000',
      flags: [
        { key: 'deep_analysis_trial', enabled: true },
        { key: 'billing', enabled: false },
        { key: 'upgrade_ctas', enabled: true },
      ],
    })

    const serialized = JSON.stringify(payload).toLowerCase()
    expect(serialized).not.toContain('email')
    expect(serialized).not.toContain('name')
    expect(serialized).not.toContain('document')
    expect(serialized).not.toContain('prompt')
    expect(serialized).not.toContain('token')
    expect(serialized).not.toContain('user_agent')
    expect(serialized).not.toContain('ip_address')
  })

  it('ignores unknown keys and drops an invalid or missing browser id', () => {
    const unknown = {
      upgrade_ctas: true,
      not_a_real_flag: true,
    } as unknown as FlagExposureMap
    expect(buildFlagExposurePayload(unknown, 'abc-123')).toEqual({
      anonymous_id: 'abc-123',
      flags: [{ key: 'upgrade_ctas', enabled: true }],
    })

    expect(buildFlagExposurePayload({ upgrade_ctas: true }, 'person@example.com')).toBeNull()
    expect(buildFlagExposurePayload({ upgrade_ctas: true }, 'has spaces')).toBeNull()
    expect(buildFlagExposurePayload({ upgrade_ctas: true }, null)).toBeNull()
    expect(buildFlagExposurePayload({}, 'abc-123')).toBeNull()
  })

  it('publishes exactly the six operational flag keys', () => {
    expect([...OPERATIONAL_FLAG_KEYS]).toEqual([
      'trial_limits',
      'deep_analysis_trial',
      'compile_timeouts',
      'task_priority',
      'billing',
      'upgrade_ctas',
    ])
  })
})

describe('admin flag exposure surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminFlagExposure.tsx')
  const apiClient = read('../lib/api-client.ts')
  const transport = read('../lib/analytics/flag-exposure.ts')
  const context = read('../contexts/FeatureFlagsContext.tsx')

  it('is wired into the operational feature-flags tab', () => {
    expect(page).toContain(
      "import AdminFlagExposure from '@/components/admin/AdminFlagExposure'",
    )
    expect(page).toContain('<AdminFlagExposure />')
    expect(component).toContain('getAdminFlagExposure')
    expect(apiClient).toContain('/admin/analytics/flag-exposure')
    expect(apiClient).toContain('AdminFlagExposureResponse')
  })

  it('shows exposed and control counts, sample sizes and both lookbacks', () => {
    expect(component).toContain('Exposed (treatment)')
    expect(component).toContain('Control (flag off)')
    expect(component).toContain('subject sample')
    expect(component).toContain('-day window')
    expect(component).toContain('flag.windows[String(days)]')
    expect(component).toContain('data.windows ?? [7, 30]')
    expect(component).toContain('Right-censored subjects')
  })

  it('shows outcome and guardrail metrics with definitions and sample sizes', () => {
    expect(component).toContain('Metric definitions and claim policy')
    expect(component).toContain('data.metric_definitions')
    expect(component).toContain('Guardrail')
    expect(component).toContain('window.guardrails')
    expect(component).toContain('cellDetail')
    expect(component).toContain('Descriptive only')
    expect(component).toContain('data.outcome_horizon_days')
  })

  it('states five-user suppression and the no-causality policy', () => {
    expect(component).toContain('five-user rule')
    expect(component).toContain('groups with fewer than')
    expect(component).toContain('No causal claim.')
    expect(component).toContain('data.claim.message')
    expect(component).toContain('observational')
  })

  it('captures only after consent and documents server-side dedupe', () => {
    expect(context).toContain('recordFlagExposures(safe)')
    expect(transport).toContain("readAnalyticsConsent() !== 'granted'")
    expect(transport).toContain("FLAG_EXPOSURE_PATH = '/analytics/flag-exposure'")
    expect(transport).toContain("credentials: 'include'")
    expect(transport).toContain('keepalive: true')
    expect(transport).toContain('deduplicates per subject/flag/variant/UTC-day')
    expect(transport).toContain('No email')
  })
})
