/**
 * useJobStream - accumulates all typed WebSocket events into UI state.
 */

import { useEffect, useReducer, useCallback } from 'react'
import { wsClient } from '@/lib/ws-client'
import { apiClient } from '@/lib/api-client'
import type { AnyEvent } from '@/lib/event-types'
import {
  jobStreamReducer,
  initialState,
} from './useJobStream.reducer'

// Re-export everything so existing imports keep working
export type {
  LogLine,
  TimeoutError,
  JobStreamState,
  ReducerAction,
} from './useJobStream.reducer'
export { jobStreamReducer, initialState } from './useJobStream.reducer'

// ------------------------------------------------------------------ //
//  Hook                                                               //
// ------------------------------------------------------------------ //

export interface UseJobStreamResult {
  state: ReturnType<typeof jobStreamReducer>
  cancel: () => void
  reset: () => void
}

export function useJobStream(jobId: string | null): UseJobStreamResult {
  const [state, dispatch] = useReducer(jobStreamReducer, initialState)

  useEffect(() => {
    if (!jobId) return

    dispatch({ type: '__reset__' })

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

  // REST polling fallback: real-time job events are delivered via Redis Pub/Sub
  // from the worker to the API process. When that fanout does not reach this
  // client (e.g. cross-container Pub/Sub on serverless Redis in production), the
  // WS subscribes but never receives a terminal event, so the PDF never loads.
  // Poll the authoritative job state/result and synthesize the terminal event.
  // The reducer ignores post-terminal transitions, so this never conflicts with
  // a WS event that arrives first.
  useEffect(() => {
    if (!jobId) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const poll = async () => {
      try {
        const snap = await apiClient.getJobState(jobId)
        if (stopped) return
        if (snap?.status === 'completed') {
          let result: Record<string, unknown> = {}
          try {
            const res = (await apiClient.getJobResult(jobId)) as unknown as Record<string, unknown>
            result = (res?.result as Record<string, unknown>) ?? res ?? {}
          } catch {
            /* result fetch best-effort */
          }
          if (stopped) return
          dispatch({
            type: 'job.completed',
            job_id: jobId,
            pdf_job_id: (result.pdf_job_id as string) ?? jobId,
            ats_score: result.ats_score,
            ats_details: result.ats_details,
            changes_made: result.changes_made,
            compilation_time: result.compilation_time,
            optimization_time: result.optimization_time,
            tokens_used: result.tokens_used,
            page_count: result.page_count,
          } as unknown as AnyEvent)
          return // terminal → stop polling
        }
        if (snap?.status === 'failed') {
          dispatch({
            type: 'job.failed',
            job_id: jobId,
            error: (snap as unknown as Record<string, unknown>)?.error ?? 'Job failed',
          } as unknown as AnyEvent)
          return
        }
      } catch {
        /* transient — keep polling */
      }
      if (!stopped) timer = setTimeout(poll, 4000)
    }

    // Delay the first poll so a healthy WS stream gets the first chance.
    timer = setTimeout(poll, 4000)
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
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
