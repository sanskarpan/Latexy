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
  type JobStreamState,
  type ReducerAction,
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
//  job.retrying                                                       //
// ------------------------------------------------------------------ //

/**
 * Transient event published by latex_worker/orchestrator when Celery
 * reschedules an attempt. It is not part of AnyEvent because it carries no
 * outcome — but without handling it the UI freezes on the previous stage for
 * the whole retry backoff (up to ~10 minutes).
 */
export interface JobRetryingEvent {
  type: 'job.retrying'
  job_id: string
  worker_id: string
  stage: string
  attempt: number
}

export type StreamAction = ReducerAction | JobRetryingEvent

/** jobStreamReducer plus the events the shared reducer does not model. */
export function streamReducer(state: JobStreamState, action: StreamAction): JobStreamState {
  if (action.type === 'job.retrying') {
    return {
      ...state,
      status: 'processing',
      stage: action.stage,
      message: `Retrying ${action.stage.replace(/_/g, ' ')} (attempt ${action.attempt})`,
    }
  }
  return jobStreamReducer(state, action)
}

// ------------------------------------------------------------------ //
//  Hook                                                               //
// ------------------------------------------------------------------ //

export interface UseJobStreamResult {
  state: JobStreamState
  cancel: () => void
  reset: () => void
}

/** Server rejections we retry rather than fail on — the WS layer throttles at
 *  20 msg/s per connection and recovers on its own. */
const RATE_LIMIT_RETRY_DELAY = 500 // ms
const MAX_RATE_LIMIT_RETRIES = 5

export function useJobStream(jobId: string | null): UseJobStreamResult {
  const [state, dispatch] = useReducer(streamReducer, initialState)

  useEffect(() => {
    if (!jobId) return

    dispatch({ type: '__reset__' })

    const handleEvent = (event: AnyEvent) => {
      if (event.job_id === jobId) {
        dispatch(event)
      }
    }

    let rateLimitRetries = 0
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    // Server-side rejections ('forbidden', 'invalid_request', …) never produce
    // job events, so without this the stream would sit at 'idle' forever.
    // The 'error' emitter is shared by every mounted stream, so only act on
    // frames that belong to this job: the server tags per-job rejections with
    // job_id. Untagged frames are connection-wide (invalid_json,
    // unknown_message_type) or come from an older server — attribute them only
    // when this is the sole subscription, otherwise one bad frame would fail
    // every job on the page.
    const handleServerError = (err: { code: string; message: string; job_id?: string }) => {
      if (err.job_id ? err.job_id !== jobId : wsClient.subscriptionCount > 1) return

      if (err.code === 'rate_limited' && rateLimitRetries < MAX_RATE_LIMIT_RETRIES) {
        rateLimitRetries++
        retryTimer = setTimeout(() => wsClient.subscribe(jobId), RATE_LIMIT_RETRY_DELAY)
        return
      }
      dispatch({
        type: 'job.failed',
        event_id: `ws-error-${err.code}`,
        job_id: jobId,
        timestamp: Date.now() / 1000,
        sequence: 0,
        stage: '',
        error_code: err.code,
        error_message: err.message,
        retryable: err.code === 'rate_limited',
      })
    }

    wsClient.on('event', handleEvent)
    wsClient.on('error', handleServerError)
    // No explicit last_event_id: ws-client replays the whole stream ("0") for a
    // first subscription — events published before this frame reaches the
    // server (job.queued, or job.completed for a fast job) would otherwise
    // never be seen — and resumes from the watermark when another listener is
    // already streaming this job, so that listener gets no duplicate replay.
    wsClient.subscribe(jobId)

    return () => {
      if (retryTimer !== null) clearTimeout(retryTimer)
      wsClient.off('event', handleEvent)
      wsClient.off('error', handleServerError)
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
    let attempts = 0
    const MAX_POLLS = 150 // ~10 min at 4s — cap so a wedged job can't poll forever
    let timer: ReturnType<typeof setTimeout> | null = null

    const poll = async () => {
      attempts += 1
      try {
        const snap = await apiClient.getJobState(jobId)
        if (stopped) return
        if (snap?.status === 'cancelled') {
          dispatch({ type: 'job.cancelled', job_id: jobId } as unknown as AnyEvent)
          return // terminal → stop polling
        }
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
          // Reducer reads error_message/error_code/retryable/stage (not `error`).
          dispatch({
            type: 'job.failed',
            job_id: jobId,
            error_message: 'Job failed',
            error_code: 'unknown',
            retryable: false,
            stage: '',
          } as unknown as AnyEvent)
          return
        }
      } catch {
        /* transient — keep polling */
      }
      if (!stopped && attempts < MAX_POLLS) timer = setTimeout(poll, 4000)
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
