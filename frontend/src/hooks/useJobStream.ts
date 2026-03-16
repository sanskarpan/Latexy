/**
 * useJobStream - accumulates all typed WebSocket events into UI state.
 */

import { useEffect, useReducer, useCallback } from 'react'
import { wsClient } from '@/lib/ws-client'
import type { AnyEvent, ATSDeepAnalysis } from '@/lib/event-types'

// ------------------------------------------------------------------ //
//  State shape                                                        //
// ------------------------------------------------------------------ //

export interface LogLine {
  source: string
  line: string
  is_error: boolean
}

export interface ATSDetails {
  category_scores: Record<string, number>
  recommendations: string[]
  strengths: string[]
  warnings: string[]
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
  error: string | null
  errorCode: string | null
  retryable: boolean
}

const initialState: JobStreamState = {
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
  error: null,
  errorCode: null,
  retryable: false,
}

// ------------------------------------------------------------------ //
//  Reducer                                                            //
// ------------------------------------------------------------------ //

type ReducerAction = AnyEvent | { type: '__reset__' }

function jobStreamReducer(state: JobStreamState, action: ReducerAction): JobStreamState {
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
      }

    case 'job.cancelled':
      return { ...state, status: 'cancelled', percent: 0, message: 'Cancelled' }

    default:
      return state
  }
}

// ------------------------------------------------------------------ //
//  Hook                                                               //
// ------------------------------------------------------------------ //

export interface UseJobStreamResult {
  state: JobStreamState
  cancel: () => void
  reset: () => void
}

export function useJobStream(jobId: string | null): UseJobStreamResult {
  const [state, dispatch] = useReducer(jobStreamReducer, initialState)

  useEffect(() => {
    if (!jobId) return

    const handleEvent = (event: AnyEvent) => {
      if (event.job_id === jobId) {
        dispatch(event)
      }
    }

    wsClient.on('event', handleEvent)
    wsClient.subscribe(jobId)

    return () => {
      wsClient.off('event', handleEvent)
      wsClient.unsubscribe(jobId)
    }
  }, [jobId])

  const cancel = useCallback(() => {
    if (jobId) wsClient.cancelJob(jobId)
  }, [jobId])

  const reset = useCallback(() => {
    dispatch({ type: '__reset__' })
  }, [])

  return { state, cancel, reset }
}
