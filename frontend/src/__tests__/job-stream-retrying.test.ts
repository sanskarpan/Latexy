import { describe, test, expect } from 'vitest'
import { streamReducer } from '../hooks/useJobStream'
import { initialState } from '../hooks/useJobStream.reducer'

// ─── job.retrying ─────────────────────────────────────────────────────────────
//
// Workers publish job.retrying when Celery reschedules an attempt. The shared
// reducer does not model it, so useJobStream wraps it — without this the UI
// would sit on the previous stage for the whole retry backoff.

describe('streamReducer — job.retrying', () => {
  test('keeps the job processing and reports the attempt', () => {
    const s = streamReducer(
      { ...initialState, status: 'processing', stage: 'llm_optimization', percent: 40 },
      { type: 'job.retrying', job_id: 'job-1', worker_id: 'latex-1', stage: 'latex_compilation', attempt: 2 },
    )
    expect(s.status).toBe('processing')
    expect(s.stage).toBe('latex_compilation')
    expect(s.message).toBe('Retrying latex compilation (attempt 2)')
    expect(s.percent).toBe(40)
  })

  test('delegates every other event to jobStreamReducer', () => {
    const s = streamReducer(initialState, {
      event_id: 'evt-1',
      job_id: 'job-1',
      timestamp: 1000,
      sequence: 1,
      type: 'job.queued',
      job_type: 'latex',
      user_id: null,
      estimated_seconds: 10,
    })
    expect(s.status).toBe('queued')
  })
})
