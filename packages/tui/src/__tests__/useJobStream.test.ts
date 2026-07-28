import { describe, it, expect, beforeEach } from 'vitest'
import { createJobController, handleFatalServerError } from '../hooks/useJobStream.js'
import { $messages, addMessage, clearMessages, $activeJobId } from '../stores/messages.js'
import type { JobCompletedEvent } from '../lib/event-types.js'

describe('JobController.onComplete', () => {
  beforeEach(() => {
    clearMessages()
    $activeJobId.set(null)
  })

  it('builds the compile_result card from the top-level job.completed fields', () => {
    const ctrl = createJobController('job-1')
    const toolMsgId = addMessage({ role: 'tool_use', content: 'compiling', jobId: 'job-1' })
    ctrl.setToolMsgId(toolMsgId)

    // Exactly what latex_worker publishes for a plain compile — no `result` wrapper, and a
    // hardcoded ats_score of 0 with empty ats_details because no ATS stage ran
    const ev: JobCompletedEvent = {
      event_id: 'e1', job_id: 'job-1', timestamp: Date.now(), sequence: 5,
      type: 'job.completed',
      pdf_job_id: 'job-1',
      ats_score: 0,
      ats_details: {},
      compilation_time: 1.25,
      optimization_time: 0,
      page_count: 2,
      compiler: 'xelatex',
    }
    ctrl.onComplete(ev)

    const card = $messages.get().find(m => m.role === 'compile_result')
    expect(card).toBeDefined()
    expect(card?.resultData).toMatchObject({
      pages: 2,
      compilationTimeMs: 1250,
      pdfUrl: '/download/job-1',
      // must NOT be 0 — that would render a bogus "0/100 — Poor" ATS row
      atsScore: null,
      compiler: 'xelatex',
    })
    const tool = $messages.get().find(m => m.id === toolMsgId)
    expect(tool?.toolState).toBe('success')
    expect(tool?.toolResult).toMatchObject({ page_count: 2, compiler: 'xelatex', ats_score: null })
  })

  it('surfaces a real ATS score when the orchestrator actually scored the resume', () => {
    const ctrl = createJobController('job-2')
    ctrl.onComplete({
      event_id: 'e2', job_id: 'job-2', timestamp: Date.now(), sequence: 7,
      type: 'job.completed',
      pdf_job_id: 'job-2',
      ats_score: 82.5,
      ats_details: { category_scores: { keywords: 90 } },
      page_count: 1,
    })
    const card = $messages.get().find(m => m.role === 'compile_result')
    expect(card?.resultData).toMatchObject({ atsScore: 82.5 })
  })

  it('keeps a genuine zero score when ats_details proves ATS ran', () => {
    const ctrl = createJobController('job-3')
    ctrl.onComplete({
      event_id: 'e3', job_id: 'job-3', timestamp: Date.now(), sequence: 3,
      type: 'job.completed',
      pdf_job_id: 'job-3',
      ats_score: 0,
      ats_details: { warnings: ['empty resume'] },
      page_count: 1,
    })
    const card = $messages.get().find(m => m.role === 'compile_result')
    expect(card?.resultData).toMatchObject({ atsScore: 0 })
  })
})

describe('handleFatalServerError', () => {
  beforeEach(() => {
    clearMessages()
    $activeJobId.set(null)
  })

  it('fails the in-flight job and clears the spinner on a forbidden frame', () => {
    const ctrl = createJobController('job-9')
    const toolMsgId = addMessage({ role: 'tool_use', content: 'compiling', jobId: 'job-9' })
    ctrl.setToolMsgId(toolMsgId)
    $activeJobId.set('job-9')

    handleFatalServerError({ code: 'forbidden', message: 'Access denied for this job' })

    expect($activeJobId.get()).toBeNull()
    const tool = $messages.get().find(m => m.id === toolMsgId)
    expect(tool?.toolState).toBe('error')
    const err = $messages.get().find(m => m.role === 'error')
    expect(err?.content).toContain('forbidden')
  })

  it('fails only the rejected job when the frame is tagged with a job_id', () => {
    // ws_routes._send_error tags per-job rejections, so a forbidden subscribe for one job
    // must not kill the sibling job streaming on the same socket
    const badCtrl = createJobController('job-bad')
    const badTool = addMessage({ role: 'tool_use', content: 'compiling', jobId: 'job-bad' })
    badCtrl.setToolMsgId(badTool)

    const goodCtrl = createJobController('job-good')
    const goodTool = addMessage({ role: 'tool_use', content: 'compiling', jobId: 'job-good' })
    goodCtrl.setToolMsgId(goodTool)
    $activeJobId.set('job-good')

    handleFatalServerError({
      code: 'forbidden',
      message: 'Access denied for this job',
      job_id: 'job-bad',
    })

    expect($messages.get().find(m => m.id === badTool)?.toolState).toBe('error')
    expect($messages.get().find(m => m.id === goodTool)?.toolState).toBeUndefined()
    // the surviving job still owns the spinner
    expect($activeJobId.get()).toBe('job-good')

    // ...and it can still complete normally
    goodCtrl.onComplete({
      event_id: 'e3', job_id: 'job-good', timestamp: Date.now(), sequence: 1,
      type: 'job.completed', pdf_job_id: 'job-good', page_count: 1,
    })
    expect($messages.get().find(m => m.id === goodTool)?.toolState).toBe('success')
    expect($activeJobId.get()).toBeNull()
  })

  it('ignores a tagged frame for a job this client is not tracking', () => {
    const ctrl = createJobController('job-mine')
    const toolMsgId = addMessage({ role: 'tool_use', content: 'compiling', jobId: 'job-mine' })
    ctrl.setToolMsgId(toolMsgId)
    $activeJobId.set('job-mine')

    handleFatalServerError({ code: 'forbidden', message: 'nope', job_id: 'job-someone-else' })

    expect($activeJobId.get()).toBe('job-mine')
    expect($messages.get().find(m => m.role === 'error')).toBeUndefined()
    expect($messages.get().find(m => m.id === toolMsgId)?.toolState).toBeUndefined()
  })

  it('ignores non-fatal codes such as the soft rate_limited throttle', () => {
    const ctrl = createJobController('job-10')
    const toolMsgId = addMessage({ role: 'tool_use', content: 'compiling', jobId: 'job-10' })
    ctrl.setToolMsgId(toolMsgId)
    $activeJobId.set('job-10')

    handleFatalServerError({ code: 'rate_limited', message: 'Too many messages' })

    expect($activeJobId.get()).toBe('job-10')
    expect($messages.get().find(m => m.role === 'error')).toBeUndefined()
    expect($messages.get().find(m => m.id === toolMsgId)?.toolState).toBeUndefined()
  })
})
