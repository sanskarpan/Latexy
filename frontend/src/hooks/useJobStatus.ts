/**
 * useJobStatus — thin wrapper around useJobStream that keeps the
 * existing public interface so callers don't need to change.
 *
 * Real-time updates come from the WebSocket via useJobStream.
 * REST polling fallback via apiClient.getJobState() when WS is unavailable.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'

// ------------------------------------------------------------------ //
//  Public interface (unchanged from previous version)                 //
// ------------------------------------------------------------------ //

export interface UseJobStatusOptions {
  autoSubscribe?: boolean
  pollInterval?: number
  onStatusChange?: (status: { status: string; percent: number; stage: string }) => void
  onComplete?: (result: { job_id: string; success: boolean; result?: Record<string, unknown> }) => void
  onError?: (error: string) => void
}

export interface UseJobStatusResult {
  status: {
    status: string
    progress: number
    message: string
    created_at?: number
    updated_at?: number
    estimated_completion?: number
  } | null
  result: { job_id: string; success: boolean; result?: Record<string, unknown> } | null
  isLoading: boolean
  error: string | null
  progress: number
  isComplete: boolean
  isFailed: boolean
  refresh: () => Promise<void>
  cancel: () => Promise<void>
  clearError: () => void
}

// ------------------------------------------------------------------ //
//  REST fallback polling bounds                                        //
// ------------------------------------------------------------------ //

const POLL_INTERVAL_MS = 5000
/** Consecutive getJobState() failures after which the fallback gives up. */
const MAX_CONSECUTIVE_POLL_FAILURES = 3
/** Hard backstop: no job outlives this, so neither should the fallback. */
const MAX_POLL_DURATION_MS = 10 * 60 * 1000

// ------------------------------------------------------------------ //
//  Hook                                                                //
// ------------------------------------------------------------------ //

export function useJobStatus(
  jobId: string | null,
  options: UseJobStatusOptions = {}
): UseJobStatusResult {
  const { onStatusChange, onComplete, onError } = options

  const onStatusChangeRef = useRef(onStatusChange)
  const onCompleteRef = useRef(onComplete)
  const onErrorRef = useRef(onError)

  // Keep refs current
  useEffect(() => { onStatusChangeRef.current = onStatusChange }, [onStatusChange])
  useEffect(() => { onCompleteRef.current = onComplete }, [onComplete])
  useEffect(() => { onErrorRef.current = onError }, [onError])

  const { state, cancel: streamCancel, reset } = useJobStream(jobId)

  /** job_id onComplete has already been fired for — the REST fallback polls on
   *  a 5s interval and must not re-announce the same completion every tick. */
  const completedForRef = useRef<string | null>(null)

  const fireComplete = useCallback(
    (payload: { job_id: string; success: boolean; result?: Record<string, unknown> }) => {
      if (!jobId || completedForRef.current === jobId) return
      completedForRef.current = jobId
      onCompleteRef.current?.(payload)
    },
    [jobId]
  )

  // ── Fire callbacks on state transitions ─────────────────────────
  useEffect(() => {
    if (!jobId || state.status === 'idle') return

    if (onStatusChangeRef.current) {
      onStatusChangeRef.current({
        status: state.status,
        percent: state.percent,
        stage: state.stage,
      })
    }
  }, [jobId, state.status, state.stage, state.percent])

  useEffect(() => {
    if (!jobId || state.status !== 'completed') return
    fireComplete({
      job_id: state.pdfJobId ?? jobId,
      success: true,
      result: {
        overall_score: state.atsScore,
        category_scores: state.atsDetails?.category_scores,
        recommendations: state.atsDetails?.recommendations,
        warnings: state.atsDetails?.warnings,
        strengths: state.atsDetails?.strengths,
        pdf_job_id: state.pdfJobId,
        changes_made: state.changesMade,
        compilation_time: state.compilationTime,
        optimization_time: state.optimizationTime,
        tokens_used: state.tokensUsed,
        timestamp: new Date().toISOString(),
      } as Record<string, unknown>,
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, state.status])

  useEffect(() => {
    if (!jobId || state.status !== 'failed' || !state.error) return
    if (onErrorRef.current) onErrorRef.current(state.error)
  }, [jobId, state.status, state.error])

  // ── REST polling fallback ────────────────────────────────────────
  // job_id for which a REST snapshot already reported a terminal status. Needed
  // because the stream stays at 'idle' when the WS delivered nothing, which
  // would otherwise keep the poll running (and re-firing) forever.
  const [fallbackTerminalFor, setFallbackTerminalFor] = useState<string | null>(null)

  // The stream sits at 'idle' precisely when the WebSocket delivered nothing —
  // which is exactly when the fallback is needed — so 'idle' counts as active.
  const streamIsActive =
    (state.status === 'idle' || state.status === 'queued' || state.status === 'processing') &&
    fallbackTerminalFor !== jobId

  /** The REST snapshot can be unavailable for the whole life of a job (expired
   *  meta, a job submitted through a path that never wrote a snapshot, a 403).
   *  Since errors are non-terminal by design, bound the fallback so it can
   *  never turn into an endless request stream for a mounted component. */
  const [pollStoppedFor, setPollStoppedFor] = useState<string | null>(null)
  const consecutiveFailuresRef = useRef(0)

  const refresh = useCallback(async () => {
    if (!jobId) return
    try {
      const snapshot = await apiClient.getJobState(jobId)
      consecutiveFailuresRef.current = 0
      // Only apply while the stream has not reached a terminal state of its own,
      // so we never overwrite a result that arrived via WebSocket.
      if (!streamIsActive) return

      // If the REST snapshot shows a terminal status that the WS hasn't
      // delivered yet, fire the appropriate callback.
      if (snapshot.status === 'completed') {
        setFallbackTerminalFor(jobId)
        fireComplete({
          job_id: jobId,
          success: true,
          result: snapshot as unknown as Record<string, unknown>,
        })
      } else if (snapshot.status === 'failed') {
        setFallbackTerminalFor(jobId)
        if (onErrorRef.current) onErrorRef.current('Job failed')
      } else if (onStatusChangeRef.current) {
        // Propagate progress update from REST snapshot
        onStatusChangeRef.current({
          status: snapshot.status,
          percent: snapshot.percent ?? 0,
          stage: snapshot.stage ?? '',
        })
      }
    } catch {
      // WebSocket is the primary update mechanism, so a failing snapshot is not
      // itself an error — but give up after a few in a row rather than polling
      // an endpoint that will never answer.
      consecutiveFailuresRef.current += 1
      if (consecutiveFailuresRef.current >= MAX_CONSECUTIVE_POLL_FAILURES) {
        setPollStoppedFor(jobId)
      }
    }
  }, [jobId, streamIsActive, fireComplete])

  // Poll while the job may still be running (fallback for a WebSocket that
  // never connected or that missed the events entirely). Polls once
  // immediately so a job that already finished is picked up without waiting a
  // full interval, and stops after MAX_POLL_DURATION_MS as a hard backstop.
  useEffect(() => {
    if (!jobId || !streamIsActive || pollStoppedFor === jobId) return

    consecutiveFailuresRef.current = 0
    refresh()

    const interval = setInterval(refresh, POLL_INTERVAL_MS)
    const stopTimer = setTimeout(() => setPollStoppedFor(jobId), MAX_POLL_DURATION_MS)
    return () => {
      clearInterval(interval)
      clearTimeout(stopTimer)
    }
  // `refresh` is deliberately excluded: it is re-created on every state change
  // and would restart the interval (and re-fire the immediate poll) each time.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, streamIsActive, pollStoppedFor])

  const cancel = useCallback(async () => {
    if (!jobId) return
    streamCancel()
    try {
      await apiClient.cancelJob(jobId)
    } catch {
      // Cancel flag is also set via WS cancel message; REST is supplemental
    }
  }, [jobId, streamCancel])

  const clearError = useCallback(() => {
    // Dispatch __reset__ through useJobStream to clear error state in the reducer
    reset()
  }, [reset])

  // ── Map stream state to legacy shape ────────────────────────────
  const status =
    state.status === 'idle'
      ? null
      : {
          status: state.status,
          progress: state.percent,
          message: state.message,
        }

  const result =
    state.status === 'completed' && state.pdfJobId
      ? {
          job_id: state.pdfJobId,
          success: true,
          result: {
            pdf_job_id: state.pdfJobId,
            ats_score: state.atsScore,
            ats_details: state.atsDetails,
            changes_made: state.changesMade,
            compilation_time: state.compilationTime,
            optimization_time: state.optimizationTime,
            tokens_used: state.tokensUsed,
          } as Record<string, unknown>,
        }
      : null

  return {
    status,
    result,
    isLoading: state.status === 'queued' || state.status === 'processing',
    error: state.error,
    progress: state.percent,
    isComplete: state.status === 'completed',
    isFailed: state.status === 'failed',
    refresh,
    cancel,
    clearError,
  }
}
