import type { Page } from '@playwright/test'
import { describe, expect, it, vi } from 'vitest'
import { observeRealPreview, semanticFieldHitTarget } from '../../e2e/real-preview/observe-real-preview'

const origin = 'http://127.0.0.1:8030'
const jobId = '11111111-1111-4111-8111-111111111111'

function observer() {
  const get = vi.fn(async () => ({ ok: (): boolean => true, json: async () => ({ status: 'completed' }) }))
  const page = { on: vi.fn(), request: { get } } as unknown as Page
  return { observed: observeRealPreview(page, origin), get }
}

describe('real preview observational state reads', () => {
  it('carries only the exact observed admission fingerprint with a bounded request', async () => {
    const { observed, get } = observer()
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: 'synthetic-unit-device',
      status: 200, jobType: 'latex_compilation', jobId })
    expect(await observed.completedState(jobId)).toBe('completed')
    expect(get).toHaveBeenCalledExactlyOnceWith(`${origin}/jobs/${jobId}/state`, {
      headers: { 'X-Device-Fingerprint': 'synthetic-unit-device' }, timeout: 15_000,
    })
  })

  it('refuses unknown jobs or missing identities before any request', async () => {
    const { observed, get } = observer()
    await expect(observed.completedState(jobId)).rejects.toThrow(/observed guest admission identity/)
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: '',
      status: 200, jobType: 'latex_compilation', jobId })
    await expect(observed.completedState(jobId)).rejects.toThrow(/observed guest admission identity/)
    expect(get).not.toHaveBeenCalled()
  })

  it('does not borrow another observed job identity for state reads', async () => {
    const { observed, get } = observer()
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: 'first-unit-device',
      status: 200, jobType: 'latex_compilation', jobId })
    const otherJobId = '22222222-2222-4222-8222-222222222222'
    await expect(observed.completedState(otherJobId)).rejects.toThrow(/observed guest admission identity/)
    expect(get).not.toHaveBeenCalled()
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: 'second-unit-device',
      status: 200, jobType: 'latex_compilation', jobId: otherJobId })
    await observed.completedState(otherJobId)
    expect(get).toHaveBeenCalledExactlyOnceWith(`${origin}/jobs/${otherJobId}/state`, {
      headers: { 'X-Device-Fingerprint': 'second-unit-device' }, timeout: 15_000,
    })
  })

  it('keeps failed state reads as failures without reporting their response contents', async () => {
    const { observed, get } = observer()
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: 'synthetic-unit-device',
      status: 200, jobType: 'latex_compilation', jobId })
    get.mockResolvedValue({ ok: () => false, json: async () => ({ status: 'failed' }) })
    await expect(observed.completedState(jobId)).rejects.toThrow('The real job state could not be read')
  })

  it('uses one exact semantic hit target when the same field wraps into multiple overlays', async () => {
    const lineTargets = [{ focus: vi.fn() }, { focus: vi.fn() }]
    const getByRole = vi.fn(() => ({ first: () => lineTargets[0] }))
    const target = semanticFieldHitTarget({ getByRole } as unknown as Page, 'synthetic wrapped field')
    await target.focus()
    expect(getByRole).toHaveBeenCalledExactlyOnceWith('button', {
      name: 'Edit resume field: synthetic wrapped field', exact: true,
    })
    expect(target).toBe(lineTargets[0])
    expect(lineTargets[0].focus).toHaveBeenCalledOnce()
    expect(lineTargets[1].focus).not.toHaveBeenCalled()
  })
})
