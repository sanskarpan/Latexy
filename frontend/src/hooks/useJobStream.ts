/**
 * useJobStream - accumulates all typed WebSocket events into UI state.
 */

import { useEffect, useReducer, useCallback, useRef } from 'react'
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

export type StreamAction = ReducerAction | JobRetryingEvent | {
  type: '__recovery_unavailable__'
  job_id: string
}

const OUTPUT_UNAVAILABLE_MESSAGE = 'Job completed, but its generated output is unavailable.'

/** jobStreamReducer plus the events the shared reducer does not model. */
export function streamReducer(state: JobStreamState, action: StreamAction): JobStreamState {
  if (action.type === '__recovery_unavailable__') {
    if (state.status === 'cancelled' || state.status === 'failed') return state
    // This is a client delivery error, not a new worker terminal decision.
    // A missed-output WS completion must not hide it behind first-writer-wins.
    return {
      ...state,
      status: 'failed',
      stage: 'recovery',
      message: OUTPUT_UNAVAILABLE_MESSAGE,
      error: OUTPUT_UNAVAILABLE_MESSAGE,
      errorCode: 'output_unavailable',
      retryable: false,
      timeoutError: null,
    }
  }
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
  applySnapshot: (snapshot: {
    status: 'queued' | 'processing'
    stage: string
    percent: number
    message?: string
  }) => void
}

/** Server rejections we retry rather than fail on — the WS layer throttles at
 *  20 msg/s per connection and recovers on its own. */
const RATE_LIMIT_RETRY_DELAY = 500 // ms
const MAX_RATE_LIMIT_RETRIES = 5

type RecoverableJobResult = Awaited<ReturnType<typeof apiClient.getJobResult>> | null

/**
 * Rebuild the terminal event sequence from the canonical REST result. Keeping
 * this pure makes the missed-event path testable without a live WebSocket and
 * ensures every replay uses the exact job id supplied by its caller.
 */
export function buildJobResultRecoveryEvents(jobId: string, result: RecoverableJobResult): StreamAction[] {
  const events: StreamAction[] = []
  // The result endpoint is owner-scoped, but a proxy/cache or a stale client
  // response must not be relabeled as this job and exposed in the UI.
  if (!result || result.job_id !== jobId) return events
  if (result.recovery_complete === false) {
    return [{ type: '__recovery_unavailable__', job_id: jobId }]
  }
  if (!result.success) return events
  if (typeof result?.extracted_text === 'string') {
    events.push({
      type: 'job.pdf_extracted',
      job_id: jobId,
      text: result.extracted_text,
      page_count: result.page_count ?? 1,
    } as unknown as AnyEvent)
  }

  const deepAnalysis = result?.deep_analysis
  if (deepAnalysis && typeof deepAnalysis.overall_score === 'number') {
    events.push({
      type: 'ats.deep_complete',
      event_id: `rest-recovery-${jobId}`,
      job_id: jobId,
      timestamp: Date.now() / 1000,
      sequence: 0,
      overall_score: deepAnalysis.overall_score,
      overall_feedback: deepAnalysis.overall_feedback,
      sections: deepAnalysis.sections,
      ats_compatibility: deepAnalysis.ats_compatibility,
      job_match: deepAnalysis.job_match,
      tokens_used: deepAnalysis.tokens_used ?? result?.tokens_used ?? 0,
      analysis_time: deepAnalysis.analysis_time ?? result?.analysis_time ?? 0,
      multi_dim_scores: deepAnalysis.multi_dim_scores,
      industry_key: deepAnalysis.industry_key,
      industry_label: deepAnalysis.industry_label,
    } as unknown as AnyEvent)
  }

  if (typeof result?.cover_letter_latex === 'string' && result.cover_letter_latex.length > 0) {
    events.push({
      type: 'llm.complete',
      event_id: `rest-recovery-${jobId}-cover-letter`,
      job_id: jobId,
      timestamp: Date.now() / 1000,
      sequence: 0,
      full_content: result.cover_letter_latex,
      tokens_total: result.tokens_used ?? 0,
    } as unknown as AnyEvent)
  }

  events.push({
    type: 'job.completed',
    job_id: jobId,
    // Null is authoritative for jobs that do not produce a PDF artifact.
    pdf_job_id: result?.pdf_job_id ?? null,
    ats_score: result?.ats_score ?? null,
    ats_details: result?.ats_details ?? null,
    changes_made: result?.changes_made ?? [],
    compilation_time: result?.compilation_time ?? 0,
    optimization_time: result?.optimization_time ?? 0,
    tokens_used: result?.tokens_used ?? 0,
    page_count: result?.page_count,
  } as unknown as AnyEvent)
  return events
}

export function useJobStream(jobId: string | null): UseJobStreamResult {
  const [state, dispatch] = useReducer(streamReducer, initialState)
  const committedJobIdRef = useRef(jobId)
  const requestedJobIdRef = useRef(jobId)
  // This ref is intentionally updated during render only for stale callback
  // gating. State ownership uses committedJobIdRef below, so StrictMode or a
  // concurrent re-render cannot accidentally unmask the previous job state.
  requestedJobIdRef.current = jobId
  // A prop switch renders before the reset effect below flushes. Do not expose
  // the previous job's completed/content state during that one render; doing
  // so lets a page start a compile or PDF fetch for the newly selected job.
  const stateForJob = committedJobIdRef.current === jobId ? state : initialState

  useEffect(() => {
    committedJobIdRef.current = jobId
    dispatch({ type: '__reset__' })
    if (!jobId) return

    const handleEvent = (event: AnyEvent) => {
      if (requestedJobIdRef.current === jobId && event.job_id === jobId) {
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
      if (requestedJobIdRef.current !== jobId) return
      if (err.job_id ? err.job_id !== jobId : wsClient.subscriptionCount > 1) return

      if (err.code === 'rate_limited' && rateLimitRetries < MAX_RATE_LIMIT_RETRIES) {
        rateLimitRetries++
        retryTimer = setTimeout(() => {
          if (requestedJobIdRef.current === jobId) wsClient.subscribe(jobId)
        }, RATE_LIMIT_RETRY_DELAY)
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
  // The reducer ignores conflicting post-terminal transitions while allowing a
  // same-job completion to enrich fields missing from an earlier WS event.
  useEffect(() => {
    if (!jobId) return
    let stopped = false
    let attempts = 0
    const MAX_POLLS = 157 // initial fast recovery, then ~10 minutes at four seconds
    const pollInterval = () => attempts < 8 ? 750 : 4000
    let timer: ReturnType<typeof setTimeout> | null = null
    let inFlight = false
    let terminal = false
    const isCurrent = () => !stopped && requestedJobIdRef.current === jobId

    const poll = async () => {
      if (!isCurrent() || inFlight || terminal || attempts >= MAX_POLLS) return
      inFlight = true
      attempts += 1
      try {
        const snap = await apiClient.getJobState(jobId)
        if (!isCurrent()) return
        if (snap?.status === 'cancelled') {
          dispatch({ type: 'job.cancelled', job_id: jobId } as unknown as AnyEvent)
          terminal = true
          return // terminal → stop polling
        }
        if (snap?.status === 'completed') {
          let result: Awaited<ReturnType<typeof apiClient.getJobResult>> | null = null
          try {
            result = await apiClient.getJobResult(jobId)
          } catch {
            /* result fetch best-effort */
          }
          if (!isCurrent()) return

          // Unlike a briefly missing Redis result, a bounded integrity marker
          // is an explicit delivery failure. Stop polling without re-enqueueing
          // or rewriting the already-completed server decision.
          if (result?.job_id === jobId && result.recovery_complete === false) {
            for (const event of buildJobResultRecoveryEvents(jobId, result)) dispatch(event)
            terminal = true
            return
          }

          // The state snapshot and result are written by separate Redis
          // operations. A completed snapshot can therefore briefly be visible
          // before /result (and its PDF artifact) is readable. Keep polling in
          // that window instead of synthesizing a terminal event with a guessed
          // job id; doing so makes the page stop retrying a still-propagating
          // PDF and leaves the preview on its placeholder forever.
          if (!result?.success) {
            if (isCurrent() && attempts < MAX_POLLS) timer = setTimeout(poll, pollInterval())
            return
          }

          // The worker publishes these events on the healthy WS path, but the
          // REST result is authoritative when Pub/Sub or stream replay missed
          // them. Preserve an explicit null PDF id for non-PDF jobs. A result
          // for another job is rejected and retried rather than relabeled.
          const recoveryEvents = buildJobResultRecoveryEvents(jobId, result)
          if (recoveryEvents.length === 0) {
            if (isCurrent() && attempts < MAX_POLLS) timer = setTimeout(poll, pollInterval())
            return
          }
          for (const event of recoveryEvents) dispatch(event)
          terminal = true
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
          terminal = true
          return
        }
        if (snap?.status === 'queued' || snap?.status === 'processing') {
          dispatch({
            type: '__snapshot__',
            status: snap.status,
            stage: snap.stage ?? '',
            percent: snap.percent ?? 0,
          })
        }
      } catch {
        /* transient — keep polling */
      } finally {
        inFlight = false
      }
      if (isCurrent() && attempts < MAX_POLLS) timer = setTimeout(poll, pollInterval())
    }

    // Recover fast cache hits immediately; slow jobs back off to four seconds.
    timer = setTimeout(poll, 0)
    const recoverOnReconnect = () => {
      if (timer) clearTimeout(timer)
      void poll()
    }
    wsClient.on('connected', recoverOnReconnect)
    return () => {
      stopped = true
      wsClient.off('connected', recoverOnReconnect)
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  const cancel = useCallback(() => {
    if (jobId) wsClient.cancelJob(jobId)
  }, [jobId])

  const reset = useCallback(() => {
    dispatch({ type: '__reset__' })
  }, [])

  const applySnapshot = useCallback((snapshot: {
    status: 'queued' | 'processing'
    stage: string
    percent: number
    message?: string
  }) => {
    dispatch({ type: '__snapshot__', ...snapshot })
  }, [])

  return { state: stateForJob, cancel, reset, applySnapshot }
}
