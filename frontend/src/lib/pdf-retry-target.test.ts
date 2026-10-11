import { describe, expect, it } from 'vitest'
import { resolveRetryableCompletedPdfJobId } from './pdf-retry-target'

const idle = { status: 'idle', pdfJobId: null }

describe('resolveRetryableCompletedPdfJobId', () => {
  it('retries only the active job represented by an owned completed stream', () => {
    expect(resolveRetryableCompletedPdfJobId('job-1', true, {
      status: 'completed',
      pdfJobId: 'job-1',
    }, idle)).toBe('job-1')
    expect(resolveRetryableCompletedPdfJobId('job-1', true, idle, {
      status: 'completed',
      pdfJobId: 'job-1',
    })).toBe('job-1')
  })

  it('rejects stale, incomplete, and unowned job ids', () => {
    expect(resolveRetryableCompletedPdfJobId('job-old', true, {
      status: 'completed',
      pdfJobId: 'job-current',
    }, idle)).toBeNull()
    expect(resolveRetryableCompletedPdfJobId('job-1', true, {
      status: 'running',
      pdfJobId: 'job-1',
    }, idle)).toBeNull()
    expect(resolveRetryableCompletedPdfJobId('job-1', false, {
      status: 'completed',
      pdfJobId: 'job-1',
    }, idle)).toBeNull()
    expect(resolveRetryableCompletedPdfJobId(null, true, {
      status: 'completed',
      pdfJobId: 'job-1',
    }, idle)).toBeNull()
  })
})
