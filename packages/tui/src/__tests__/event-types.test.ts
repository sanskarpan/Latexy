import { describe, it, expect } from 'vitest'
import type { AnyEvent, JobCompletedEvent, LLMTokenEvent, LogLineEvent } from '../lib/event-types.js'

describe('event-types', () => {
  it('JobCompletedEvent has required fields', () => {
    const ev: JobCompletedEvent = {
      event_id: 'e1', job_id: 'j1', timestamp: Date.now(),
      sequence: 1, type: 'job.completed',
      result: { success: true }, final_status: 'completed',
    }
    expect(ev.type).toBe('job.completed')
  })

  it('LLMTokenEvent carries token string', () => {
    const ev: LLMTokenEvent = {
      event_id: 'e2', job_id: 'j2', timestamp: Date.now(),
      sequence: 2, type: 'llm.token', token: 'Hello',
    }
    expect(ev.token).toBe('Hello')
  })

  it('LogLineEvent has level field', () => {
    const ev: LogLineEvent = {
      event_id: 'e3', job_id: 'j3', timestamp: Date.now(),
      sequence: 3, type: 'log.line', line: 'test', level: 'error',
    }
    expect(ev.level).toBe('error')
  })

  it('AnyEvent union covers all 14 types', () => {
    const types: AnyEvent['type'][] = [
      'job.queued', 'job.started', 'job.progress', 'job.completed',
      'job.failed', 'job.cancelled', 'job.pdf_extracted',
      'llm.token', 'llm.complete', 'log.line', 'ats.deep_complete',
      'sys.heartbeat', 'sys.error', 'document.convert_complete',
    ]
    expect(types).toHaveLength(14)
  })
})
