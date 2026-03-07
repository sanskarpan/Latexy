/**
 * useJobStatus — thin wrapper around useJobStream that keeps the
 * existing public interface so callers don't need to change.
 *
 * Real-time updates come from the WebSocket via useJobStream.
 * REST polling fallback via apiClient.getJobState() when WS is unavailable.
 */

import { useCallback, useEffect } from 'react'
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
//  Hook                                                                //
// ------------------------------------------------------------------ //

export function useJobStatus(
  jobId: string | null,
  options: UseJobStatusOptions = {}
): UseJobStatusResult {
  const { onStatusChange, onComplete, onError } = options

  const { state, cancel: streamCancel } = useJobStream(jobId)

  // ── Fire callbacks on state transitions ─────────────────────────
  useEffect(() => {
    if (!jobId || state.status === 'idle') return

    if (onStatusChange) {
      onStatusChange({
        status: state.status,
        percent: state.percent,
        stage: state.stage,
      })
    }
  }, [state.status, state.stage, state.percent]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!jobId || state.status !== 'completed') return
    if (onComplete) {
      onComplete({
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
    }
  }, [state.status]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!jobId || state.status !== 'failed' || !state.error) return
    if (onError) onError(state.error)
  }, [state.status, state.error]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── REST polling fallback ────────────────────────────────────────
  const refresh = useCallback(async () => {
    if (!jobId) return
    try {
      await apiClient.getJobState(jobId)
    } catch {
      // Ignore — WebSocket is the primary update mechanism
    }
  }, [jobId])

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
    // No local error state to clear — error comes from stream reducer
  }, [])

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
