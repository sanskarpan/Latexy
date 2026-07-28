/**
 * useJobStream - accumulates all typed WebSocket events into UI state.
 */

import { useEffect, useReducer, useCallback } from 'react'
import { wsClient } from '@/lib/ws-client'
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

  const cancel = useCallback(() => {
    if (jobId) wsClient.cancelJob(jobId)
  }, [jobId])

  const reset = useCallback(() => {
    dispatch({ type: '__reset__' })
  }, [])

  return { state, cancel, reset }
}
