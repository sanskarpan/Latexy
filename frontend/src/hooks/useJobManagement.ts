/**
 * React hook for job management and queue operations
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { 
  jobApiClient, 
  JobSubmissionRequest, 
  JobSubmissionResponse,
  JobListResponse,
  SystemHealthResponse 
} from '@/lib/job-api-client'
import { useNotifications } from '@/components/NotificationProvider'

export interface UseJobManagementOptions {
  autoRefresh?: boolean
  refreshInterval?: number
  maxJobs?: number
}

export interface UseJobManagementResult {
  // Job submission
  submitJob: (request: JobSubmissionRequest) => Promise<string | null>
  isSubmitting: boolean
  submissionError: string | null

  // Job listing
  jobs: JobListResponse | null
  isLoadingJobs: boolean
  jobsError: string | null
  refreshJobs: () => Promise<void>

  // System health
  systemHealth: SystemHealthResponse | null
  isLoadingHealth: boolean
  healthError: string | null
  refreshHealth: () => Promise<void>

  // Convenience methods
  compileLatex: (latexContent: string, deviceFingerprint?: string, userPlan?: string) => Promise<string | null>
  optimizeResume: (latexContent: string, jobDescription: string, optimizationLevel?: 'conservative' | 'balanced' | 'aggressive', userPlan?: string) => Promise<string | null>
  optimizeAndCompile: (latexContent: string, jobDescription: string, optimizationLevel?: 'conservative' | 'balanced' | 'aggressive', deviceFingerprint?: string, userPlan?: string) => Promise<string | null>
  scoreResume: (latexContent: string, jobDescription?: string, industry?: string, deviceFingerprint?: string, userPlan?: string) => Promise<string | null>

  // Utilities
  clearErrors: () => void
  getJobById: (jobId: string) => any
  getActiveJobs: () => any[]
  getCompletedJobs: () => any[]
  getFailedJobs: () => any[]
}

export function useJobManagement(options: UseJobManagementOptions = {}): UseJobManagementResult {
  const {
    autoRefresh = true,
    refreshInterval = 10000, // 10 seconds
    maxJobs = 100,
  } = options

  // Job submission state
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submissionError, setSubmissionError] = useState<string | null>(null)

  // Job listing state
  const [jobs, setJobs] = useState<JobListResponse | null>(null)
  const [isLoadingJobs, setIsLoadingJobs] = useState(false)
  const [jobsError, setJobsError] = useState<string | null>(null)

  // System health state
  const [systemHealth, setSystemHealth] = useState<SystemHealthResponse | null>(null)
  const [isLoadingHealth, setIsLoadingHealth] = useState(false)
  const [healthError, setHealthError] = useState<string | null>(null)

  const { addNotification } = useNotifications()
  const refreshIntervalRef = useRef<NodeJS.Timeout | null>(null)

  const submitJob = useCallback(async (request: JobSubmissionRequest): Promise<string | null> => {
    try {
      setIsSubmitting(true)
      setSubmissionError(null)

      const response = await jobApiClient.submitJob(request)
      
      if (response.success) {
        addNotification({
          type: 'success',
          title: 'Job Submitted',
          message: `${request.job_type} job submitted successfully`,
        })

        // Refresh jobs list to include the new job
        setTimeout(() => {
          refreshJobs()
        }, 1000)

        return response.job_id
      } else {
        throw new Error(response.message || 'Job submission failed')
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Job submission failed'
      setSubmissionError(errorMessage)
      
      addNotification({
        type: 'error',
        title: 'Job Submission Failed',
        message: errorMessage,
      })
      
      return null
    } finally {
      setIsSubmitting(false)
    }
  }, [addNotification])

  const refreshJobs = useCallback(async () => {
    try {
      setIsLoadingJobs(true)
      setJobsError(null)

      const response = await jobApiClient.listJobs(undefined, maxJobs, 0)
      setJobs(response)
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to load jobs'
      setJobsError(errorMessage)
    } finally {
      setIsLoadingJobs(false)
    }
  }, [maxJobs])

  const refreshHealth = useCallback(async () => {
    try {
      setIsLoadingHealth(true)
      setHealthError(null)

      const response = await jobApiClient.getSystemHealth()
      setSystemHealth(response)
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to load system health'
      setHealthError(errorMessage)
    } finally {
      setIsLoadingHealth(false)
    }
  }, [])

  // Convenience methods for common job types
  const compileLatex = useCallback(async (
    latexContent: string,
    deviceFingerprint?: string,
    userPlan: string = 'free'
  ): Promise<string | null> => {
    return submitJob({
      job_type: 'latex_compilation',
      latex_content: latexContent,
      device_fingerprint: deviceFingerprint,
      user_plan: userPlan,
      metadata: {
        submitted_via: 'frontend',
        timestamp: new Date().toISOString(),
      },
    })
  }, [submitJob])

  const optimizeResume = useCallback(async (
    latexContent: string,
    jobDescription: string,
    optimizationLevel: 'conservative' | 'balanced' | 'aggressive' = 'balanced',
    userPlan: string = 'free'
  ): Promise<string | null> => {
    return submitJob({
      job_type: 'llm_optimization',
      latex_content: latexContent,
      job_description: jobDescription,
      optimization_level: optimizationLevel,
      user_plan: userPlan,
      metadata: {
        submitted_via: 'frontend',
        timestamp: new Date().toISOString(),
      },
    })
  }, [submitJob])

  const optimizeAndCompile = useCallback(async (
    latexContent: string,
    jobDescription: string,
    optimizationLevel: 'conservative' | 'balanced' | 'aggressive' = 'balanced',
    deviceFingerprint?: string,
    userPlan: string = 'free'
  ): Promise<string | null> => {
    return submitJob({
      job_type: 'combined',
      latex_content: latexContent,
      job_description: jobDescription,
      optimization_level: optimizationLevel,
      device_fingerprint: deviceFingerprint,
      user_plan: userPlan,
      metadata: {
        submitted_via: 'frontend',
        timestamp: new Date().toISOString(),
      },
    })
  }, [submitJob])

  const scoreResume = useCallback(async (
    latexContent: string,
    jobDescription?: string,
    industry?: string,
    deviceFingerprint?: string,
    userPlan: string = 'free'
  ): Promise<string | null> => {
    return submitJob({
      job_type: 'ats_scoring',
      latex_content: latexContent,
      job_description: jobDescription,
      industry: industry,
      device_fingerprint: deviceFingerprint,
      user_plan: userPlan,
      metadata: {
        submitted_via: 'frontend',
        timestamp: new Date().toISOString(),
      },
    })
  }, [submitJob])

  const clearErrors = useCallback(() => {
    setSubmissionError(null)
    setJobsError(null)
    setHealthError(null)
  }, [])

  const getJobById = useCallback((jobId: string) => {
    return jobs?.jobs.find(job => job.job_id === jobId) || null
  }, [jobs])

  const getActiveJobs = useCallback(() => {
    return jobs?.jobs.filter(job => ['pending', 'processing'].includes(job.status)) || []
  }, [jobs])

  const getCompletedJobs = useCallback(() => {
    return jobs?.jobs.filter(job => job.status === 'completed') || []
  }, [jobs])

  const getFailedJobs = useCallback(() => {
    return jobs?.jobs.filter(job => job.status === 'failed') || []
  }, [jobs])

  // Auto-refresh jobs and health
  useEffect(() => {
    if (!autoRefresh) return

    const refresh = async () => {
      await Promise.all([
        refreshJobs(),
        refreshHealth(),
      ])
    }

    // Initial load
    refresh()

    // Set up interval
    refreshIntervalRef.current = setInterval(refresh, refreshInterval)

    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current)
      }
    }
  }, [autoRefresh, refreshInterval, refreshJobs, refreshHealth])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current)
      }
    }
  }, [])

  return {
    // Job submission
    submitJob,
    isSubmitting,
    submissionError,

    // Job listing
    jobs,
    isLoadingJobs,
    jobsError,
    refreshJobs,

    // System health
    systemHealth,
    isLoadingHealth,
    healthError,
    refreshHealth,

    // Convenience methods
    compileLatex,
    optimizeResume,
    optimizeAndCompile,
    scoreResume,

    // Utilities
    clearErrors,
    getJobById,
    getActiveJobs,
    getCompletedJobs,
    getFailedJobs,
  }
}
