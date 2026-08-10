/**
 * JobController must settle cleanly and must not double-apply a replayed event.
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { JobController } from '../hooks/useJobStream.js'
import { $messages, clearMessages, $activeJobId } from '../stores/messages.js'
import type { JobCompletedEvent, LogLineEvent } from '../lib/event-types.js'

function logLine(seq: number, line: string): LogLineEvent {
  return {
    event_id: `1700000000000-${seq}`, job_id: 'job-1', timestamp: 0,
    sequence: seq, type: 'log.line', line, stream: 'stdout',
  } as LogLineEvent
}

function completed(): JobCompletedEvent {
  return {
    event_id: 'done-1', job_id: 'job-1', timestamp: 0, sequence: 99,
    type: 'job.completed', page_count: 1,
  } as JobCompletedEvent
}

beforeEach(() => { clearMessages(); $activeJobId.set(null) })

describe('streamed LLM output settles when the job ends', () => {
  it('a completion arriving before the flush timer does not strand a streaming message', async () => {
    const ctrl = new JobController('job-1')
    ctrl.setToolMsgId('tool-1')

    ctrl.onLLMToken('partial answer')  // schedules a 16ms flush
    ctrl.onComplete(completed())       // lands first

    await new Promise(r => setTimeout(r, 60))

    const assistant = $messages.get().filter(m => m.role === 'assistant')
    expect(assistant, 'the generated text must still be shown').toHaveLength(1)
    expect(assistant[0]!.content).toBe('partial answer')
    expect(
      assistant[0]!.streaming,
      'a finished answer left rendering as in-progress, forever',
    ).toBe(false)
  })

  it('leaves no pending timer once the job has settled', async () => {
    const ctrl = new JobController('job-1')
    ctrl.setToolMsgId('tool-1')
    ctrl.onLLMToken('abc')
    ctrl.onComplete(completed())

    const before = $messages.get().length
    await new Promise(r => setTimeout(r, 60))
    // A surviving flush timer would append or mutate a message after settling.
    expect($messages.get().length).toBe(before)
  })
})

describe('replayed events are applied once', () => {
  it('the same log line delivered twice renders once', () => {
    const ctrl = new JobController('job-1')
    ctrl.onLogLine(logLine(1, 'This is pass 1.'))
    ctrl.onLogLine(logLine(2, 'Output written.'))
    ctrl.onLogLine(logLine(1, 'This is pass 1.'))   // reconnect replay
    ctrl.onLogLine(logLine(2, 'Output written.'))

    const card = $messages.get().find(m => m.role === 'log_stream')
    const lines = (card?.resultData as { lines: string[] }).lines
    expect(lines).toEqual(['This is pass 1.', 'Output written.'])
  })

  it('genuinely repeated text with distinct event ids is kept', () => {
    // pdflatex really does print the same line on each pass — only the event id
    // makes a replay distinguishable from a repeat.
    const ctrl = new JobController('job-1')
    ctrl.onLogLine(logLine(1, 'Rerun to get cross-references right.'))
    ctrl.onLogLine(logLine(2, 'Rerun to get cross-references right.'))

    const card = $messages.get().find(m => m.role === 'log_stream')
    expect((card?.resultData as { lines: string[] }).lines).toHaveLength(2)
  })

  it('a replayed completion does not add a second result card', () => {
    const ctrl = new JobController('job-1')
    ctrl.setToolMsgId('tool-1')
    ctrl.onComplete(completed())
    ctrl.onComplete(completed())
    expect($messages.get().filter(m => m.role === 'compile_result')).toHaveLength(1)
  })

  it('a replayed llm token is not appended twice', async () => {
    const ctrl = new JobController('job-1')
    const tok = { event_id: 'tok-1' }
    ctrl.onLLMToken('hello', tok)
    ctrl.onLLMToken('hello', tok)
    ctrl.onComplete(completed())
    await new Promise(r => setTimeout(r, 40))
    expect($messages.get().find(m => m.role === 'assistant')?.content).toBe('hello')
  })
})
