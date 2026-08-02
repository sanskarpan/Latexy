import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient } from '../lib/api-client'
import { EMPTY_INTAKE, intakeActiveCount, intakeIsEmpty, type GuidedIntake } from '../lib/guided-intake'

function mockFetch(responseBody: object = { success: true, job_id: 'job-1', message: 'ok' }) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: {},
      json: () => Promise.resolve(responseBody),
      text: () => Promise.resolve(JSON.stringify(responseBody)),
    })
  )
}

function lastBody(): Record<string, unknown> {
  const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
  return JSON.parse(init.body as string)
}

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

describe('intakeIsEmpty', () => {
  test('EMPTY_INTAKE is empty', () => {
    expect(intakeIsEmpty(EMPTY_INTAKE)).toBe(true)
  })

  test('any single populated field makes it non-empty', () => {
    expect(intakeIsEmpty({ ...EMPTY_INTAKE, industry: 'Fintech' })).toBe(false)
    expect(intakeIsEmpty({ ...EMPTY_INTAKE, seniority: 'Senior' })).toBe(false)
    expect(intakeIsEmpty({ ...EMPTY_INTAKE, tone: 'Formal' })).toBe(false)
    expect(intakeIsEmpty({ ...EMPTY_INTAKE, emphasize: ['AWS'] })).toBe(false)
    expect(intakeIsEmpty({ ...EMPTY_INTAKE, downplay: ['internships'] })).toBe(false)
  })

  test('whitespace-only text fields are treated as empty', () => {
    expect(intakeIsEmpty({ ...EMPTY_INTAKE, industry: '   ', tone: '\t' })).toBe(true)
  })
})

describe('intakeActiveCount', () => {
  test('counts each populated field once', () => {
    expect(intakeActiveCount(EMPTY_INTAKE)).toBe(0)
    expect(
      intakeActiveCount({
        industry: 'Fintech',
        seniority: 'Senior',
        tone: 'Formal',
        emphasize: ['AWS', 'K8s'],
        downplay: ['internships'],
      })
    ).toBe(5)
    expect(intakeActiveCount({ ...EMPTY_INTAKE, emphasize: ['AWS', 'K8s'] })).toBe(1)
  })
})

describe('optimizeAndCompile guided-intake plumbing', () => {
  const LATEX = '\\documentclass{article}\\begin{document}Hi\\end{document}'

  test('forwards all guided-intake fields into the combined-job body', async () => {
    mockFetch()
    const intake: GuidedIntake = {
      industry: 'Fintech',
      seniority: 'Senior',
      tone: 'Impact-focused',
      emphasize: ['AWS migration', 'team leadership'],
      downplay: ['early internships'],
    }

    await apiClient.optimizeAndCompile({
      latex_content: LATEX,
      job_description: 'Backend role',
      optimization_level: 'balanced',
      industry: intake.industry,
      seniority: intake.seniority,
      tone: intake.tone,
      emphasize: intake.emphasize,
      downplay: intake.downplay,
    })

    const body = lastBody()
    expect(body.job_type).toBe('combined')
    expect(body.industry).toBe('Fintech')
    expect(body.seniority).toBe('Senior')
    expect(body.tone).toBe('Impact-focused')
    expect(body.emphasize).toEqual(['AWS migration', 'team leadership'])
    expect(body.downplay).toEqual(['early internships'])
  })

  test('omits guided-intake fields when not provided', async () => {
    mockFetch()

    await apiClient.optimizeAndCompile({
      latex_content: LATEX,
      optimization_level: 'balanced',
    })

    const body = lastBody()
    expect(body.job_type).toBe('combined')
    expect('seniority' in body).toBe(false)
    expect('tone' in body).toBe(false)
    expect('emphasize' in body).toBe(false)
    expect('downplay' in body).toBe(false)
  })
})
