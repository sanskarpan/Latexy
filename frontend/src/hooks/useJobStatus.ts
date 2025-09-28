/**
 * React hook for job status tracking with real-time updates
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { jobApiClient, JobStatusResponse, JobResultResponse } from '@/lib/job-api-client'
import { useWebSocket } from '@/components/WebSocketProvider'
import { useNotifications } from '@/components/NotificationProvider'

export interface UseJobStatusOptions {
  autoSubscribe?: boolean
  pollInterval?: number
  onStatusChange?: (status: JobStatusResponse) => void
  onComplete?: (result: JobResultResponse) => void
  onError?: (error: string) => void
}

export interface UseJobStatusResult {
  status: JobStatusResponse | null
  result: JobResultResponse | null
  isLoading: boolean
  error: string | null
  progress: number
  isComplete: boolean
  isFailed: boolean
  refresh: () => Promise<void>
  cancel: () => Promise<void>
  clearError: () => void
}

export function useJobStatus(
  jobId: string | null,
  options: UseJobStatusOptions = {}
): UseJobStatusResult {
  const {
    autoSubscribe = true,
    pollInterval = 2000,
    onStatusChange,
    onComplete,
    onError,
  } = options

  const [status, setStatus] = useState<JobStatusResponse | null>(null)
  const [result, setResult] = useState<JobResultResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { subscribeToJob, unsubscribeFromJob, jobUpdates, isConnected } = useWebSocket()
  const { addNotification } = useNotifications()
  
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const lastStatusRef = useRef<string | null>(null)

  // Calculate derived state
  const progress = status?.progress || 0
  const isComplete = status?.status === 'completed'
  const isFailed = status?.status === 'failed'

  const clearError = useCallback(() => {
    setError(null)
  }, [])

  const fetchStatus = useCallback(async () => {
    if (!jobId) return

    try {
      setIsLoading(true)
      const statusResponse = await jobApiClient.getJobStatus(jobId)
      setStatus(statusResponse)
      
      // Call status change callback
      if (onStatusChange) {
        onStatusChange(statusResponse)
      }

      // Check if job completed and fetch result
      if (statusResponse.status === 'completed' && !result) {
        try {
          const resultResponse = await jobApiClient.getJobResult(jobId)
          setResult(resultResponse)
          
          if (onComplete) {
            onComplete(resultResponse)
          }

          // Show success notification
          addNotification({
            type: 'success',
            title: 'Job Completed',
            message: `Job ${jobId.substring(0, 8)} completed successfully`,
          })
        } catch (resultError) {
          console.error('Failed to fetch job result:', resultError)
        }
      }

      // Handle failed jobs
      if (statusResponse.status === 'failed' && lastStatusRef.current !== 'failed') {
        const errorMessage = statusResponse.message || 'Job failed'
        setError(errorMessage)
        
        if (onError) {
          onError(errorMessage)
        }

        addNotification({
          type: 'error',
          title: 'Job Failed',
          message: `Job ${jobId.substring(0, 8)} failed: ${errorMessage}`,
        })
      }

      lastStatusRef.current = statusResponse.status

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch job status'
      setError(errorMessage)
      
      if (onError) {
        onError(errorMessage)
      }
    } finally {
      setIsLoading(false)
    }
  }, [jobId, result, onStatusChange, onComplete, onError, addNotification])

  const refresh = useCallback(async () => {
    await fetchStatus()
  }, [fetchStatus])

  const cancel = useCallback(async () => {
    if (!jobId) return

    try {
      await jobApiClient.cancelJob(jobId)
      
      addNotification({
        type: 'info',
        title: 'Job Cancelled',
        message: `Job ${jobId.substring(0, 8)} has been cancelled`,
      })

      // Refresh status to get updated state
      await fetchStatus()
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to cancel job'
      setError(errorMessage)
      
      addNotification({
        type: 'error',
        title: 'Cancellation Failed',
        message: errorMessage,
      })
    }
  }, [jobId, fetchStatus, addNotification])

  // Handle WebSocket updates
  useEffect(() => {
    if (!jobId || !jobUpdates[jobId]) return

    const update = jobUpdates[jobId]
    
    // Update status with WebSocket data
    setStatus(prev => prev ? {
      ...prev,
      status: update.status as any,
      progress: update.progress,
      message: update.message,
      updated_at: Date.now() / 1000,
    } : null)

    // Handle completion via WebSocket
    if (update.status === 'completed' && update.result && !result) {
      const resultResponse: JobResultResponse = {
        job_id: jobId,
        success: true,
        result: update.result,
        completed_at: update.completed_at,
      }
      
      setResult(resultResponse)
      
      if (onComplete) {
        onComplete(resultResponse)
      }

      addNotification({
        type: 'success',
        title: 'Job Completed',
        message: `Job ${jobId.substring(0, 8)} completed successfully`,
      })
    }

    // Handle failure via WebSocket
    if (update.status === 'failed' && update.error) {
      setError(update.error)
      
      if (onError) {
        onError(update.error)
      }

      addNotification({
        type: 'error',
        title: 'Job Failed',
        message: `Job ${jobId.substring(0, 8)} failed: ${update.error}`,
      })
    }
  }, [jobId, jobUpdates, result, onComplete, onError, addNotification])

  // Subscribe to WebSocket updates
  useEffect(() => {
    if (!jobId || !autoSubscribe) return

    if (isConnected) {
      subscribeToJob(jobId)
    }

    return () => {
      if (jobId) {
        unsubscribeFromJob(jobId)
      }
    }
  }, [jobId, autoSubscribe, isConnected, subscribeToJob, unsubscribeFromJob])

  // Initial fetch and polling setup
  useEffect(() => {
    if (!jobId) {
      setStatus(null)
      setResult(null)
      setError(null)
      return
    }

    // Initial fetch
    fetchStatus()

    // Set up polling for non-terminal states (when WebSocket is not available)
    const shouldPoll = !isConnected && status && !['completed', 'failed', 'cancelled'].includes(status.status)
    
    if (shouldPoll && pollInterval > 0) {
      pollIntervalRef.current = setInterval(fetchStatus, pollInterval)
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
  }, [jobId, fetchStatus, pollInterval, isConnected, status?.status])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [])

  return {
    status,
    result,
    isLoading,
    error,
    progress,
    isComplete,
    isFailed,
    refresh,
    cancel,
    clearError,
  }
}
