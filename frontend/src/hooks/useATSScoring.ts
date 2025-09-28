/**
 * React hook for ATS scoring functionality
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { 
  jobApiClient, 
  ATSScoreRequest, 
  ATSScoreResponse,
  JobDescriptionAnalysisRequest,
  JobDescriptionAnalysisResponse,
  ATSRecommendationsRequest,
  ATSRecommendationsResponse 
} from '@/lib/job-api-client'
import { useNotifications } from '@/components/NotificationProvider'
import { useJobStatus } from './useJobStatus'

export interface UseATSScoringOptions {
  autoAnalyzeJD?: boolean
  defaultIndustry?: string
  userPlan?: string
  deviceFingerprint?: string
}

export interface UseATSScoringResult {
  // Scoring
  scoreResume: (request: Omit<ATSScoreRequest, 'user_plan' | 'device_fingerprint'>) => Promise<string | null>
  scoringJobId: string | null
  scoringResult: ATSScoreResponse | null
  isScoringLoading: boolean
  scoringError: string | null

  // Job Description Analysis
  analyzeJobDescription: (request: Omit<JobDescriptionAnalysisRequest, 'user_plan'>) => Promise<string | null>
  analysisJobId: string | null
  analysisResult: JobDescriptionAnalysisResponse | null
  isAnalysisLoading: boolean
  analysisError: string | null

  // Recommendations
  getRecommendations: (request: ATSRecommendationsRequest) => Promise<ATSRecommendationsResponse | null>
  recommendations: ATSRecommendationsResponse | null
  isRecommendationsLoading: boolean
  recommendationsError: string | null

  // Industry data
  supportedIndustries: string[]
  industryKeywords: Record<string, string[]>
  loadIndustryKeywords: (industry: string) => Promise<void>
  isIndustryLoading: boolean

  // Utilities
  clearResults: () => void
  clearErrors: () => void
}

export function useATSScoring(options: UseATSScoringOptions = {}): UseATSScoringResult {
  const {
    autoAnalyzeJD = false,
    defaultIndustry,
    userPlan = 'free',
    deviceFingerprint,
  } = options

  // Scoring state
  const [scoringJobId, setScoringJobId] = useState<string | null>(null)
  const [scoringResult, setScoringResult] = useState<ATSScoreResponse | null>(null)
  const [isScoringLoading, setIsScoringLoading] = useState(false)
  const [scoringError, setScoringError] = useState<string | null>(null)

  // Job Description Analysis state
  const [analysisJobId, setAnalysisJobId] = useState<string | null>(null)
  const [analysisResult, setAnalysisResult] = useState<JobDescriptionAnalysisResponse | null>(null)
  const [isAnalysisLoading, setIsAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)

  // Recommendations state
  const [recommendations, setRecommendations] = useState<ATSRecommendationsResponse | null>(null)
  const [isRecommendationsLoading, setIsRecommendationsLoading] = useState(false)
  const [recommendationsError, setRecommendationsError] = useState<string | null>(null)

  // Industry data state
  const [supportedIndustries, setSupportedIndustries] = useState<string[]>([])
  const [industryKeywords, setIndustryKeywords] = useState<Record<string, string[]>>({})
  const [isIndustryLoading, setIsIndustryLoading] = useState(false)

  const { addNotification } = useNotifications()
  const startTimeRef = useRef<number>(0)

  // Job status tracking for scoring
  const scoringJobStatus = useJobStatus(scoringJobId, {
    onComplete: (result) => {
      if (result.success && result.result) {
        setScoringResult({
          success: true,
          ats_score: result.result.overall_score,
          category_scores: result.result.category_scores,
          recommendations: result.result.recommendations,
          warnings: result.result.warnings,
          strengths: result.result.strengths,
          detailed_analysis: result.result.detailed_analysis,
          processing_time: (Date.now() - startTimeRef.current) / 1000,
          message: `ATS scoring completed: ${result.result.overall_score}/100`,
          timestamp: result.result.timestamp,
        })
        
        addNotification({
          type: 'success',
          title: 'ATS Scoring Complete',
          message: `Resume scored: ${result.result.overall_score}/100`,
        })
      }
      setIsScoringLoading(false)
    },
    onError: (error) => {
      setScoringError(error)
      setIsScoringLoading(false)
      addNotification({
        type: 'error',
        title: 'ATS Scoring Failed',
        message: error,
      })
    }
  })

  // Job status tracking for analysis
  const analysisJobStatus = useJobStatus(analysisJobId, {
    onComplete: (result) => {
      if (result.success && result.result) {
        setAnalysisResult({
          success: true,
          keywords: result.result.keywords,
          requirements: result.result.requirements,
          preferred_qualifications: result.result.preferred_qualifications,
          detected_industry: result.result.detected_industry,
          analysis_metrics: result.result.analysis_metrics,
          optimization_tips: result.result.optimization_tips,
          processing_time: (Date.now() - startTimeRef.current) / 1000,
          message: 'Job description analysis completed',
        })
        
        addNotification({
          type: 'success',
          title: 'Job Description Analysis Complete',
          message: `Found ${result.result.keywords?.length || 0} keywords`,
        })
      }
      setIsAnalysisLoading(false)
    },
    onError: (error) => {
      setAnalysisError(error)
      setIsAnalysisLoading(false)
      addNotification({
        type: 'error',
        title: 'Job Description Analysis Failed',
        message: error,
      })
    }
  })

  const scoreResume = useCallback(async (
    request: Omit<ATSScoreRequest, 'user_plan' | 'device_fingerprint'>
  ): Promise<string | null> => {
    try {
      setIsScoringLoading(true)
      setScoringError(null)
      setScoringResult(null)
      startTimeRef.current = Date.now()

      const response = await jobApiClient.scoreResume({
        ...request,
        user_plan: userPlan,
        device_fingerprint: deviceFingerprint,
        async_processing: true,
      })

      if (response.success && response.job_id) {
        setScoringJobId(response.job_id)
        return response.job_id
      } else if (response.success && response.ats_score !== undefined) {
        // Synchronous response
        setScoringResult(response)
        setIsScoringLoading(false)
        
        addNotification({
          type: 'success',
          title: 'ATS Scoring Complete',
          message: `Resume scored: ${response.ats_score}/100`,
        })
        
        return null
      } else {
        throw new Error(response.message || 'ATS scoring failed')
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'ATS scoring failed'
      setScoringError(errorMessage)
      setIsScoringLoading(false)
      
      addNotification({
        type: 'error',
        title: 'ATS Scoring Failed',
        message: errorMessage,
      })
      
      return null
    }
  }, [userPlan, deviceFingerprint, addNotification])

  const analyzeJobDescription = useCallback(async (
    request: Omit<JobDescriptionAnalysisRequest, 'user_plan'>
  ): Promise<string | null> => {
    try {
      setIsAnalysisLoading(true)
      setAnalysisError(null)
      setAnalysisResult(null)
      startTimeRef.current = Date.now()

      const response = await jobApiClient.analyzeJobDescription({
        ...request,
        user_plan: userPlan,
        async_processing: true,
      })

      if (response.success && response.job_id) {
        setAnalysisJobId(response.job_id)
        return response.job_id
      } else if (response.success && response.keywords) {
        // Synchronous response
        setAnalysisResult(response)
        setIsAnalysisLoading(false)
        
        addNotification({
          type: 'success',
          title: 'Job Description Analysis Complete',
          message: `Found ${response.keywords.length} keywords`,
        })
        
        return null
      } else {
        throw new Error(response.message || 'Job description analysis failed')
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Job description analysis failed'
      setAnalysisError(errorMessage)
      setIsAnalysisLoading(false)
      
      addNotification({
        type: 'error',
        title: 'Job Description Analysis Failed',
        message: errorMessage,
      })
      
      return null
    }
  }, [userPlan, addNotification])

  const getRecommendations = useCallback(async (
    request: ATSRecommendationsRequest
  ): Promise<ATSRecommendationsResponse | null> => {
    try {
      setIsRecommendationsLoading(true)
      setRecommendationsError(null)

      const response = await jobApiClient.getRecommendations(request)
      
      if (response.success) {
        setRecommendations(response)
        
        addNotification({
          type: 'success',
          title: 'Recommendations Generated',
          message: `${response.priority_improvements.length} improvements identified`,
        })
        
        return response
      } else {
        throw new Error(response.message || 'Failed to get recommendations')
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to get recommendations'
      setRecommendationsError(errorMessage)
      
      addNotification({
        type: 'error',
        title: 'Recommendations Failed',
        message: errorMessage,
      })
      
      return null
    } finally {
      setIsRecommendationsLoading(false)
    }
  }, [addNotification])

  const loadIndustryKeywords = useCallback(async (industry: string) => {
    if (industryKeywords[industry]) {
      return // Already loaded
    }

    try {
      setIsIndustryLoading(true)
      const response = await jobApiClient.getIndustryKeywords(industry)
      
      if (response.success) {
        setIndustryKeywords(prev => ({
          ...prev,
          [industry]: response.keywords,
        }))
      }
    } catch (error) {
      console.error('Failed to load industry keywords:', error)
    } finally {
      setIsIndustryLoading(false)
    }
  }, [industryKeywords])

  const clearResults = useCallback(() => {
    setScoringJobId(null)
    setScoringResult(null)
    setAnalysisJobId(null)
    setAnalysisResult(null)
    setRecommendations(null)
  }, [])

  const clearErrors = useCallback(() => {
    setScoringError(null)
    setAnalysisError(null)
    setRecommendationsError(null)
  }, [])

  // Load supported industries on mount
  useEffect(() => {
    const loadSupportedIndustries = async () => {
      try {
        const response = await jobApiClient.getSupportedIndustries()
        if (response.success) {
          setSupportedIndustries(response.industries)
          
          // Load default industry keywords if specified
          if (defaultIndustry && response.industries.includes(defaultIndustry)) {
            await loadIndustryKeywords(defaultIndustry)
          }
        }
      } catch (error) {
        console.error('Failed to load supported industries:', error)
      }
    }

    loadSupportedIndustries()
  }, [defaultIndustry, loadIndustryKeywords])

  // Auto-generate recommendations when scoring is complete
  useEffect(() => {
    if (scoringResult?.success && scoringResult.ats_score !== undefined && scoringResult.category_scores) {
      getRecommendations({
        ats_score: scoringResult.ats_score,
        category_scores: scoringResult.category_scores,
        industry: defaultIndustry,
      })
    }
  }, [scoringResult, defaultIndustry, getRecommendations])

  return {
    // Scoring
    scoreResume,
    scoringJobId,
    scoringResult,
    isScoringLoading,
    scoringError,

    // Job Description Analysis
    analyzeJobDescription,
    analysisJobId,
    analysisResult,
    isAnalysisLoading,
    analysisError,

    // Recommendations
    getRecommendations,
    recommendations,
    isRecommendationsLoading,
    recommendationsError,

    // Industry data
    supportedIndustries,
    industryKeywords,
    loadIndustryKeywords,
    isIndustryLoading,

    // Utilities
    clearResults,
    clearErrors,
  }
}
