import { describe, expect, test } from 'vitest'

import { buildJobResultRecoveryEvents, streamReducer } from '../hooks/useJobStream'
import { initialState } from '../hooks/useJobStream.reducer'

describe('durable output delivery integrity', () => {
  test.each([false, true])('explicit incomplete output is not replayed as success (%s)', (success) => {
    const events = buildJobResultRecoveryEvents('job-current', {
      job_id: 'job-current', success, recovery_complete: false,
      error_code: 'output_unavailable', omitted_output_fields: ['deep_analysis'],
      // No partial output from an incomplete result should reach the UI.
      cover_letter_latex: 'partial output', pdf_job_id: 'partial-pdf',
    })
    expect(events).toEqual([{ type: '__recovery_unavailable__', job_id: 'job-current' }])
    const state = events.reduce(streamReducer, initialState)
    expect(state).toMatchObject({
      status: 'failed', stage: 'recovery', retryable: false,
      errorCode: 'output_unavailable', streamingLatex: '', pdfJobId: null,
      error: 'Job completed, but its generated output is unavailable.',
    })
  })

  test('a WebSocket completion cannot conceal an explicit REST delivery failure', () => {
    const state = streamReducer({ ...initialState, status: 'completed', percent: 100 }, {
      type: '__recovery_unavailable__', job_id: 'job-current',
    })
    expect(state.errorCode).toBe('output_unavailable')
    expect(state.status).toBe('failed')
  })

  test.each(['cancelled', 'failed'] as const)('preserves the existing %s terminal authority', (status) => {
    const state = { ...initialState, status, errorCode: 'existing-terminal' }
    expect(streamReducer(state, {
      type: '__recovery_unavailable__', job_id: 'job-current',
    })).toBe(state)
  })

  test('rejects an incomplete result belonging to another job', () => {
    expect(buildJobResultRecoveryEvents('job-current', {
      job_id: 'job-old', success: false, recovery_complete: false,
    })).toEqual([])
  })

  test('a still-propagating result remains retryable, not an invented completion', () => {
    expect(buildJobResultRecoveryEvents('job-current', {
      job_id: 'job-current', success: false,
    })).toEqual([])
    expect(buildJobResultRecoveryEvents('job-current', null)).toEqual([])
  })
})
