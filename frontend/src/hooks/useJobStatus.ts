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

  // Keep callback refs current during render so a response that resolves
  // between render and passive effects cannot call the previous job owner.
  onStatusChangeRef.current = onStatusChange
  onCompleteRef.current = onComplete
  onErrorRef.current = onError

  const { state, cancel: streamCancel, reset, applySnapshot } = useJobStream(jobId)

  const mountedRef = useRef(true)
  const currentJobIdRef = useRef(jobId)
  const jobGenerationRef = useRef(0)

  /** job_id onComplete has already been fired for — the REST fallback polls on
   *  a 5s interval and must not re-announce the same completion every tick. */
  const completedForRef = useRef<string | null>(null)
  const consecutiveFailuresRef = useRef(0)

  // A job identity change starts a new completion generation. This also makes
  // A → B → A safe: the second A is a new request, not the already-completed A.
  if (currentJobIdRef.current !== jobId) {
    currentJobIdRef.current = jobId
    jobGenerationRef.current += 1
    completedForRef.current = null
    consecutiveFailuresRef.current = 0
  }

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      jobGenerationRef.current += 1
    }
  }, [])

  const fireComplete = useCallback(
    (payload: { job_id: string; success: boolean; result?: Record<string, unknown> }) => {
      if (!jobId || currentJobIdRef.current !== jobId || completedForRef.current === jobId) return
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
  const [fallbackTerminalGeneration, setFallbackTerminalGeneration] = useState<number | null>(null)

  // The stream sits at 'idle' precisely when the WebSocket delivered nothing —
  // which is exactly when the fallback is needed — so 'idle' counts as active.
  const streamIsActive =
    (state.status === 'idle' || state.status === 'queued' || state.status === 'processing') &&
    fallbackTerminalGeneration !== jobGenerationRef.current

  /** The REST snapshot can be unavailable for the whole life of a job (expired
   *  meta, a job submitted through a path that never wrote a snapshot, a 403).
   *  Since errors are non-terminal by design, bound the fallback so it can
   *  never turn into an endless request stream for a mounted component. */
  const [pollStoppedGeneration, setPollStoppedGeneration] = useState<number | null>(null)
  const streamIsActiveRef = useRef(streamIsActive)
  streamIsActiveRef.current = streamIsActive

  const refresh = useCallback(async () => {
    if (!jobId || !mountedRef.current) return
    const requestedJobId = jobId
    const requestedGeneration = jobGenerationRef.current
    const isCurrentRequest = () =>
      mountedRef.current &&
      currentJobIdRef.current === requestedJobId &&
      jobGenerationRef.current === requestedGeneration

    try {
      const snapshot = await apiClient.getJobState(jobId)
      if (!isCurrentRequest()) return
      consecutiveFailuresRef.current = 0
      // Only apply while the stream has not reached a terminal state of its own,
      // so we never overwrite a result that arrived via WebSocket.
      if (!streamIsActiveRef.current) return

      // The stream owns terminal completion because /state and /result are
      // committed independently. useJobStream waits for the authoritative
      // result before dispatching job.completed; this wrapper only stops its
      // duplicate progress poll here.
      if (snapshot.status === 'completed') {
        setFallbackTerminalGeneration(jobGenerationRef.current)
      } else if (snapshot.status === 'failed') {
        setFallbackTerminalGeneration(jobGenerationRef.current)
        if (onErrorRef.current) onErrorRef.current('Job failed')
      } else if (snapshot.status === 'queued' || snapshot.status === 'processing') {
        const progress = {
          status: snapshot.status,
          percent: snapshot.percent ?? 0,
          stage: snapshot.stage ?? '',
        }
        applySnapshot(progress)
        onStatusChangeRef.current?.(progress)
      }
    } catch {
      // WebSocket is the primary update mechanism, so a failing snapshot is not
      // itself an error — but give up after a few in a row rather than polling
      // an endpoint that will never answer.
      if (!isCurrentRequest()) return
      consecutiveFailuresRef.current += 1
      if (consecutiveFailuresRef.current >= MAX_CONSECUTIVE_POLL_FAILURES) {
        setPollStoppedGeneration(jobGenerationRef.current)
      }
    }
  }, [jobId, applySnapshot])

  // Poll while the job may still be running (fallback for a WebSocket that
  // never connected or that missed the events entirely). Polls once
  // immediately so a job that already finished is picked up without waiting a
  // full interval, and stops after MAX_POLL_DURATION_MS as a hard backstop.
  useEffect(() => {
    if (!jobId || !streamIsActive || pollStoppedGeneration === jobGenerationRef.current) return

    consecutiveFailuresRef.current = 0
    refresh()

    const interval = setInterval(refresh, POLL_INTERVAL_MS)
    const timerJobId = jobId
    const timerGeneration = jobGenerationRef.current
    const stopTimer = setTimeout(() => {
      if (
        mountedRef.current &&
        currentJobIdRef.current === timerJobId &&
        jobGenerationRef.current === timerGeneration
      ) {
        setPollStoppedGeneration(timerGeneration)
      }
    }, MAX_POLL_DURATION_MS)
    return () => {
      clearInterval(interval)
      clearTimeout(stopTimer)
    }
  // `refresh` is deliberately excluded: it is re-created on every state change
  // and would restart the interval (and re-fire the immediate poll) each time.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, streamIsActive, pollStoppedGeneration])

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
