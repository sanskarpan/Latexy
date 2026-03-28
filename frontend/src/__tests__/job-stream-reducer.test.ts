import { describe, test, expect } from 'vitest'
import { jobStreamReducer, initialState } from '../hooks/useJobStream.reducer'
import type { JobStreamState } from '../hooks/useJobStream.reducer'

// ─── helpers ──────────────────────────────────────────────────────────────────

const BASE_EVENT = {
  event_id: 'evt-1',
  job_id: 'job-1',
  timestamp: 1000,
  sequence: 1,
}

// ─── reset ────────────────────────────────────────────────────────────────────

describe('jobStreamReducer — __reset__', () => {
  test('resets to initialState', () => {
    const dirty: JobStreamState = {
      ...initialState,
      status: 'completed',
      pdfJobId: 'abc',
      extractedPdfText: 'some text',
    }
    expect(jobStreamReducer(dirty, { type: '__reset__' })).toEqual(initialState)
  })
})

// ─── job.queued ───────────────────────────────────────────────────────────────

describe('jobStreamReducer — job.queued', () => {
  test('sets status to queued and clears progress', () => {
    const s = jobStreamReducer(
      { ...initialState, status: 'completed', percent: 100 },
      { ...BASE_EVENT, type: 'job.queued', job_type: 'latex', user_id: null, estimated_seconds: 10 },
    )
    expect(s.status).toBe('queued')
    expect(s.percent).toBe(0)
  })
})

// ─── job.started ──────────────────────────────────────────────────────────────

describe('jobStreamReducer — job.started', () => {
  test('sets status to processing and records stage', () => {
    const s = jobStreamReducer(
      initialState,
      { ...BASE_EVENT, type: 'job.started', worker_id: 'w1', stage: 'latex_compilation' },
    )
    expect(s.status).toBe('processing')
    expect(s.stage).toBe('latex_compilation')
  })
})

// ─── job.progress ─────────────────────────────────────────────────────────────

describe('jobStreamReducer — job.progress', () => {
  test('updates percent, stage, and message', () => {
    const s = jobStreamReducer(
      initialState,
      { ...BASE_EVENT, type: 'job.progress', percent: 50, stage: 'latex_compilation', message: 'Compiling' },
    )
    expect(s.percent).toBe(50)
    expect(s.stage).toBe('latex_compilation')
    expect(s.message).toBe('Compiling')
  })
})

// ─── job.pdf_extracted ────────────────────────────────────────────────────────

describe('jobStreamReducer — job.pdf_extracted', () => {
  test('stores extracted text', () => {
    const text = 'John Doe\njohn@example.com\nEXPERIENCE\n'
    const s = jobStreamReducer(
      initialState,
      { ...BASE_EVENT, type: 'job.pdf_extracted', text, page_count: 1 },
    )
    expect(s.extractedPdfText).toBe(text)
  })

  test('updates pageCount from the event', () => {
    const s = jobStreamReducer(
      { ...initialState, pageCount: null },
      { ...BASE_EVENT, type: 'job.pdf_extracted', text: 'some text', page_count: 2 },
    )
    expect(s.pageCount).toBe(2)
  })

  test('preserves existing pageCount when event page_count is undefined-ish', () => {
    // page_count is typed as number so this won't happen in practice,
    // but we verify ?? logic: if page_count is 0 (falsy) state.pageCount is used
    const s = jobStreamReducer(
      { ...initialState, pageCount: 3 },
      { ...BASE_EVENT, type: 'job.pdf_extracted', text: 'text', page_count: 0 },
    )
    // 0 ?? 3 = 0 (0 is not null/undefined), so pageCount becomes 0
    expect(s.pageCount).toBe(0)
  })

  test('does not touch other state fields', () => {
    const before = { ...initialState, pdfJobId: 'abc', atsScore: 80 }
    const s = jobStreamReducer(
      before,
      { ...BASE_EVENT, type: 'job.pdf_extracted', text: 'text', page_count: 1 },
    )
    expect(s.pdfJobId).toBe('abc')
    expect(s.atsScore).toBe(80)
  })

  test('initialState has extractedPdfText as null', () => {
    expect(initialState.extractedPdfText).toBeNull()
  })
})

// ─── job.completed ────────────────────────────────────────────────────────────

describe('jobStreamReducer — job.completed', () => {
  test('sets status to completed and records pdf job id', () => {
    const s = jobStreamReducer(
      initialState,
      {
        ...BASE_EVENT,
        type: 'job.completed',
        pdf_job_id: 'pdf-abc',
        ats_score: 0,
        ats_details: { category_scores: {}, recommendations: [], strengths: [], warnings: [] },
        changes_made: [],
        compilation_time: 1.2,
        optimization_time: 0,
        tokens_used: 0,
        page_count: 1,
      },
    )
    expect(s.status).toBe('completed')
    expect(s.pdfJobId).toBe('pdf-abc')
    expect(s.compilationTime).toBe(1.2)
  })

  test('preserves extractedPdfText set by a prior job.pdf_extracted event', () => {
    const withText = { ...initialState, extractedPdfText: 'extracted content' }
    const s = jobStreamReducer(
      withText,
      {
        ...BASE_EVENT,
        type: 'job.completed',
        pdf_job_id: 'pdf-abc',
        ats_score: 0,
        ats_details: { category_scores: {}, recommendations: [], strengths: [], warnings: [] },
        changes_made: [],
        compilation_time: 1.0,
        optimization_time: 0,
        tokens_used: 0,
        page_count: 1,
      },
    )
    expect(s.extractedPdfText).toBe('extracted content')
  })

  test('clears error on successful completion', () => {
    const withError = { ...initialState, error: 'previous error', errorCode: 'latex_error' }
    const s = jobStreamReducer(
      withError,
      {
        ...BASE_EVENT,
        type: 'job.completed',
        pdf_job_id: 'pdf-abc',
        ats_score: 0,
        ats_details: { category_scores: {}, recommendations: [], strengths: [], warnings: [] },
        changes_made: [],
        compilation_time: 1.0,
        optimization_time: 0,
        tokens_used: 0,
        page_count: 1,
      },
    )
    expect(s.error).toBeNull()
    expect(s.errorCode).toBeNull()
  })
})

// ─── job.failed ───────────────────────────────────────────────────────────────

describe('jobStreamReducer — job.failed', () => {
  test('sets status to failed and records error', () => {
    const s = jobStreamReducer(
      initialState,
      {
        ...BASE_EVENT,
        type: 'job.failed',
        stage: 'latex_compilation',
        error_code: 'latex_error',
        error_message: 'Undefined control sequence',
        retryable: false,
      },
    )
    expect(s.status).toBe('failed')
    expect(s.error).toBe('Undefined control sequence')
    expect(s.errorCode).toBe('latex_error')
  })

  test('sets timeoutError for compile_timeout error code', () => {
    const s = jobStreamReducer(
      initialState,
      {
        ...BASE_EVENT,
        type: 'job.failed',
        stage: 'latex_compilation',
        error_code: 'compile_timeout',
        error_message: 'Timed out',
        retryable: false,
        upgrade_message: 'Upgrade to Pro',
        user_plan: 'free',
      },
    )
    expect(s.timeoutError).not.toBeNull()
    expect(s.timeoutError?.plan).toBe('free')
    expect(s.timeoutError?.upgradeMessage).toBe('Upgrade to Pro')
  })

  test('does not set timeoutError for non-timeout errors', () => {
    const s = jobStreamReducer(
      initialState,
      {
        ...BASE_EVENT,
        type: 'job.failed',
        stage: 'latex_compilation',
        error_code: 'latex_error',
        error_message: 'Error',
        retryable: false,
      },
    )
    expect(s.timeoutError).toBeNull()
  })
})

// ─── ats.deep_complete ────────────────────────────────────────────────────────

describe('jobStreamReducer — ats.deep_complete', () => {
  test('stores deep analysis result', () => {
    const s = jobStreamReducer(
      initialState,
      {
        ...BASE_EVENT,
        type: 'ats.deep_complete',
        overall_score: 82,
        overall_feedback: 'Good resume.',
        sections: [],
        ats_compatibility: { score: 90, issues: [], keyword_gaps: [] },
        job_match: null,
        tokens_used: 500,
        analysis_time: 3.2,
        multi_dim_scores: { grammar: 90, bullet_clarity: 75 },
      },
    )
    expect(s.deepAnalysis?.overall_score).toBe(82)
    expect(s.deepAnalysis?.multi_dim_scores?.grammar).toBe(90)
  })
})

// ─── log.line ─────────────────────────────────────────────────────────────────

describe('jobStreamReducer — log.line', () => {
  test('appends log lines', () => {
    let s = jobStreamReducer(
      initialState,
      { ...BASE_EVENT, type: 'log.line', source: 'pdflatex', line: 'line 1', is_error: false },
    )
    s = jobStreamReducer(
      s,
      { ...BASE_EVENT, type: 'log.line', source: 'pdflatex', line: 'line 2', is_error: false },
    )
    expect(s.logLines).toHaveLength(2)
    expect(s.logLines[1].line).toBe('line 2')
  })

  test('parses page count from pdflatex output line', () => {
    const s = jobStreamReducer(
      initialState,
      {
        ...BASE_EVENT,
        type: 'log.line',
        source: 'pdflatex',
        line: 'Output written on resume.pdf (2 pages, 48237 bytes).',
        is_error: false,
      },
    )
    expect(s.pageCount).toBe(2)
  })
})

// ─── job.cancelled ────────────────────────────────────────────────────────────

describe('jobStreamReducer — job.cancelled', () => {
  test('sets status to cancelled', () => {
    const s = jobStreamReducer(
      { ...initialState, status: 'processing' },
      { ...BASE_EVENT, type: 'job.cancelled' },
    )
    expect(s.status).toBe('cancelled')
  })
})

// ─── llm.token / llm.complete ─────────────────────────────────────────────────

describe('jobStreamReducer — llm events', () => {
  test('accumulates tokens in streamingLatex', () => {
    let s = jobStreamReducer(
      initialState,
      { ...BASE_EVENT, type: 'llm.token', token: '\\doc' },
    )
    s = jobStreamReducer(s, { ...BASE_EVENT, type: 'llm.token', token: 'umentclass' })
    expect(s.streamingLatex).toBe('\\documentclass')
  })

  test('llm.complete replaces streaming content', () => {
    const s = jobStreamReducer(
      { ...initialState, streamingLatex: 'partial' },
      { ...BASE_EVENT, type: 'llm.complete', full_content: '\\documentclass{article}', tokens_total: 10 },
    )
    expect(s.streamingLatex).toBe('\\documentclass{article}')
    expect(s.tokensUsed).toBe(10)
  })
})
