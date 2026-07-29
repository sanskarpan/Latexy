import { describe, it, expect, beforeEach } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { MessageRow } from '../components/MessageRow.js'
import { createJobController } from '../hooks/useJobStream.js'
import { $messages, clearMessages } from '../stores/messages.js'
import type { Message } from '../stores/messages.js'

/** Drive the real controller so the whole job.completed -> card path is covered. */
function cardMessage(compiler: string, atsFields: Partial<{ ats_score: number; ats_details: Record<string, unknown> }>): Message {
  clearMessages()
  const ctrl = createJobController('job-row')
  ctrl.onComplete({
    event_id: 'e1', job_id: 'job-row', timestamp: Date.now(), sequence: 1,
    type: 'job.completed', pdf_job_id: 'job-row', page_count: 1, compilation_time: 1, compiler,
    ...atsFields,
  })
  const card = $messages.get().find(m => m.role === 'compile_result')
  if (!card) throw new Error('no compile_result message')
  return card
}

describe('MessageRow compile_result', () => {
  beforeEach(() => {
    clearMessages()
  })

  it('renders the compiler reported by the job instead of the pdflatex default', () => {
    const { lastFrame } = render(<MessageRow message={cardMessage('xelatex', {})} />)
    expect(lastFrame()).toContain('xelatex')
    expect(lastFrame()).not.toContain('pdflatex')
  })

  it('renders no ATS row for a plain compile that reports the hardcoded 0.0', () => {
    const msg = cardMessage('pdflatex', { ats_score: 0, ats_details: {} })
    const { lastFrame } = render(<MessageRow message={msg} />)
    expect(lastFrame()).not.toContain('ATS Score')
  })

  it('renders the ATS row when ATS really ran', () => {
    const msg = cardMessage('pdflatex', { ats_score: 64, ats_details: { strengths: ['x'] } })
    const { lastFrame } = render(<MessageRow message={msg} />)
    expect(lastFrame()).toContain('ATS Score')
    expect(lastFrame()).toContain('64/100')
  })
})
