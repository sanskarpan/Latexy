/**
 * Pure reducer for useJobStream — no browser dependencies.
 * Extracted so it can be unit-tested in a node environment.
 */

import type { AnyEvent, ATSDeepAnalysis, ATSDetails } from '@/lib/event-types'

// ------------------------------------------------------------------ //
//  State shape                                                        //
// ------------------------------------------------------------------ //

export interface LogLine {
  source: string
  line: string
  is_error: boolean
}

export interface TimeoutError {
  plan: string
  upgradeMessage: string
}

export interface JobStreamState {
  status: 'idle' | 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'
  stage: string
  percent: number
  message: string
  /** Accumulated LLM token stream - update Monaco model directly */
  streamingLatex: string
  logLines: LogLine[]
  atsScore: number | null
  atsDetails: ATSDetails | null
  deepAnalysis: ATSDeepAnalysis | null
  changesMade: Array<{ section: string; change_type: string; reason: string }>
  pdfJobId: string | null
  compilationTime: number | null
  optimizationTime: number | null
  tokensUsed: number | null
  /** Page count from last successful pdflatex compile */
  pageCount: number | null
  /** Plain text extracted from the compiled PDF via pdftotext (ATS pre-flight) */
  extractedPdfText: string | null
  error: string | null
  errorCode: string | null
  retryable: boolean
  /** Set when error_code === 'compile_timeout' — used to show upgrade CTA */
  timeoutError: TimeoutError | null
}

export const initialState: JobStreamState = {
  status: 'idle',
  stage: '',
  percent: 0,
  message: '',
  streamingLatex: '',
  logLines: [],
  atsScore: null,
  atsDetails: null,
  deepAnalysis: null,
  changesMade: [],
  pdfJobId: null,
  compilationTime: null,
  optimizationTime: null,
  tokensUsed: null,
  pageCount: null,
  extractedPdfText: null,
  error: null,
  errorCode: null,
  retryable: false,
  timeoutError: null,
}

// ------------------------------------------------------------------ //
//  Reducer                                                            //
// ------------------------------------------------------------------ //

export type ReducerAction = AnyEvent | { type: '__reset__' }

export function jobStreamReducer(state: JobStreamState, action: ReducerAction): JobStreamState {
  if (action.type === '__reset__') return { ...initialState }
  const event = action as AnyEvent
  switch (event.type) {
    case 'job.queued':
      return { ...state, status: 'queued', stage: '', percent: 0 }

    case 'job.started':
      return { ...state, status: 'processing', stage: event.stage, message: `Starting ${event.stage}` }

    case 'job.progress':
      return {
        ...state,
        status: 'processing',
        stage: event.stage,
        percent: event.percent,
        message: event.message,
      }

    case 'llm.token':
      return { ...state, streamingLatex: state.streamingLatex + event.token }

    case 'llm.complete':
      return {
        ...state,
        streamingLatex: event.full_content,
        tokensUsed: event.tokens_total,
      }

    case 'log.line': {
      const pageCountMatch = event.line?.match(/Output written on .+?\((\d+) page/)
      return {
        ...state,
        logLines: [
          ...state.logLines,
          { source: event.source, line: event.line, is_error: event.is_error },
        ],
        ...(pageCountMatch ? { pageCount: parseInt(pageCountMatch[1], 10) } : {}),
      }
    }

    case 'job.completed':
      return {
        ...state,
        status: 'completed',
        percent: 100,
        stage: '',
        message: 'Completed',
        pdfJobId: event.pdf_job_id,
        atsScore: event.ats_score,
        atsDetails: event.ats_details as ATSDetails,
        changesMade: event.changes_made,
        compilationTime: event.compilation_time,
        optimizationTime: event.optimization_time,
        tokensUsed: event.tokens_used,
        pageCount: event.page_count ?? state.pageCount,
        error: null,
        errorCode: null,
        timeoutError: null,
      }

    case 'job.pdf_extracted':
      return {
        ...state,
        extractedPdfText: event.text,
        pageCount: event.page_count ?? state.pageCount,
      }

    case 'ats.deep_complete':
      return {
        ...state,
        deepAnalysis: {
          overall_score: event.overall_score,
          overall_feedback: event.overall_feedback,
          sections: event.sections,
          ats_compatibility: event.ats_compatibility,
          job_match: event.job_match,
          tokens_used: event.tokens_used,
          analysis_time: event.analysis_time,
          multi_dim_scores: event.multi_dim_scores,
        },
      }

    case 'job.failed':
      return {
        ...state,
        status: 'failed',
        stage: event.stage,
        error: event.error_message,
        errorCode: event.error_code,
        retryable: event.retryable,
        streamingLatex: event.optimized_latex ?? state.streamingLatex,
        changesMade: event.changes_made ?? state.changesMade,
        timeoutError: event.error_code === 'compile_timeout'
          ? {
              plan: event.user_plan ?? 'free',
              upgradeMessage: event.upgrade_message ?? 'Upgrade to Pro for a 4-minute compile timeout',
            }
          : null,
      }

    case 'job.cancelled':
      return { ...state, status: 'cancelled', percent: 0, message: 'Cancelled' }

    default:
      return state
  }
}
