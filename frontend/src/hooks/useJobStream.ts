/**
 * useJobStream - accumulates all typed WebSocket events into UI state.
 *
 * Uses useReducer so every event type has a pure, testable update path.
 * Subscribe on mount, unsubscribe on unmount or jobId change.
 *
 * Critical performance note:
 * - llm.token events append to streamingLatex in the reducer (string concat).
 * - Callers should use streamingLatex for direct Monaco model mutation
 *   (editorRef.current.getModel().setValue(streamingLatex)) NOT React state
 *   per token.  useJobStream only triggers a re-render when the field
 *   actually changes, but even so, callers should debounce if needed.
 */

import { useEffect, useReducer, useCallback } from 'react'
import { wsClient } from '@/lib/ws-client'
import type { AnyEvent } from '@/lib/event-types'

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
  changesMade: Array<{ section: string; change_type: string; reason: string }>
  pdfJobId: string | null
  compilationTime: number | null
  optimizationTime: number | null
  tokensUsed: number | null
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
  changesMade: [],
  pdfJobId: null,
  compilationTime: null,
  optimizationTime: null,
  tokensUsed: null,
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
      // Append token - caller updates Monaco model in a useEffect
      return { ...state, streamingLatex: state.streamingLatex + event.token }

    case 'llm.complete':
      return {
        ...state,
        streamingLatex: event.full_content,
        tokensUsed: event.tokens_total,
      }

    case 'log.line':
      return {
        ...state,
        logLines: [
          ...state.logLines,
          { source: event.source, line: event.line, is_error: event.is_error },
        ],
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
        error: null,
        errorCode: null,
      }

    case 'job.failed':
      return {
        ...state,
        status: 'failed',
        stage: event.stage,
        error: event.error_message,
        errorCode: event.error_code,
        retryable: event.retryable,
        // Fix 3: preserve LLM work when compilation fails
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

  // Subscribe / unsubscribe when jobId changes
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
