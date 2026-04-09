/**
 * job-api-client.ts — Compatibility shim used by useATSScoring and useJobManagement.
 * Wraps the apiClient from api-client.ts with domain-specific methods and types.
 */

import { apiClient } from './api-client'

// ------------------------------------------------------------------ //
//  ATS Scoring types                                                  //
// ------------------------------------------------------------------ //

export interface ATSScoreRequest {
  latex_content: string
  job_description?: string
  industry?: string
  user_plan?: string
  device_fingerprint?: string
  async_processing?: boolean
}

export type CategoryScores = Record<string, number>

export interface ATSScoreResponse {
  success: boolean
  job_id?: string
  ats_score?: number
  category_scores?: CategoryScores
  recommendations?: string[]
  warnings?: string[]
  strengths?: string[]
  detailed_analysis?: Record<string, unknown>
  processing_time?: number
  message?: string
  timestamp?: string
  industry_key?: string
  industry_label?: string
}

// ------------------------------------------------------------------ //
//  Job Description Analysis types                                     //
// ------------------------------------------------------------------ //

export interface JobDescriptionAnalysisRequest {
  job_description: string
  user_plan?: string
  async_processing?: boolean
}

export interface JobDescriptionAnalysisResponse {
  success: boolean
  job_id?: string
  keywords?: string[]
  requirements?: string[]
  preferred_qualifications?: string[]
  detected_industry?: string
  analysis_metrics?: Record<string, unknown>
  optimization_tips?: string[]
  processing_time?: number
  message?: string
}

// ------------------------------------------------------------------ //
//  Recommendations types                                              //
// ------------------------------------------------------------------ //

export interface PriorityImprovement {
  category: string
  priority: 'high' | 'medium' | 'low'
  current_score: number
  potential_improvement: number
  recommended_actions: string[]
}

export interface ATSRecommendationsRequest {
  ats_score: number
  category_scores?: CategoryScores
  industry?: string
}

export interface ATSRecommendationsResponse {
  success: boolean
  priority_improvements: PriorityImprovement[]
  message?: string
}

// ------------------------------------------------------------------ //
//  Job Management types                                               //
// ------------------------------------------------------------------ //

export interface JobSubmissionRequest {
  job_type: 'latex_compilation' | 'llm_optimization' | 'combined' | 'ats_scoring'
  latex_content?: string
  job_description?: string
  optimization_level?: 'conservative' | 'balanced' | 'aggressive'
  user_plan?: string
  device_fingerprint?: string
  industry?: string
  metadata?: Record<string, unknown>
}

export interface JobSubmissionResponse {
  success: boolean
  job_id: string
  message: string
}

export interface JobInfo {
  job_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'
  stage?: string
  progress?: number
  message?: string
  created_at?: string
  updated_at?: string
  metadata?: Record<string, string>
}

export interface JobListResponse {
  jobs: JobInfo[]
  total: number
  total_count?: number
}

export interface SystemHealthResponse {
  status: string
  queue_depths: Record<string, number>
  worker_count: number
  websocket_connections?: number
  active_jobs_count?: number
}

export interface IndustryKeywordsResponse {
  success: boolean
  keywords: string[]
}

export interface SupportedIndustriesResponse {
  success: boolean
  industries: string[]
}

// ------------------------------------------------------------------ //
//  jobApiClient — thin wrapper around apiClient                      //
// ------------------------------------------------------------------ //

class JobApiClient {
  async scoreResume(req: ATSScoreRequest): Promise<ATSScoreResponse> {
    const res = await apiClient.submitJob({
      job_type: 'ats_scoring',
      latex_content: req.latex_content,
      job_description: req.job_description,
      industry: req.industry,
      user_plan: req.user_plan,
      device_fingerprint: req.device_fingerprint,
    })
    return { success: res.success, job_id: res.job_id, message: res.message }
  }

  async analyzeJobDescription(
    req: JobDescriptionAnalysisRequest
  ): Promise<JobDescriptionAnalysisResponse> {
    return apiClient.analyzeJobDescription({
      job_description: req.job_description,
      user_plan: req.user_plan,
      async_processing: req.async_processing ?? true,
    })
  }

  async getRecommendations(
    req: ATSRecommendationsRequest
  ): Promise<ATSRecommendationsResponse> {
    const res = await apiClient.getAtsRecommendations({
      ats_score: req.ats_score,
      category_scores: req.category_scores ?? {},
      industry: req.industry,
    })
    return { success: res.success, priority_improvements: res.priority_improvements as PriorityImprovement[] }
  }

  async getIndustryKeywords(industry: string): Promise<IndustryKeywordsResponse> {
    const res = await apiClient.getIndustryKeywords(industry)
    return { success: res.success, keywords: res.keywords }
  }

  async getSupportedIndustries(): Promise<SupportedIndustriesResponse> {
    const res = await apiClient.getSupportedIndustries()
    return { success: res.success, industries: res.industries }
  }

  async submitJob(req: JobSubmissionRequest): Promise<JobSubmissionResponse> {
    const res = await apiClient.submitJob({
      job_type: req.job_type,
      latex_content: req.latex_content,
      job_description: req.job_description,
      optimization_level: req.optimization_level,
      user_plan: req.user_plan,
      device_fingerprint: req.device_fingerprint,
      industry: req.industry,
    })
    return { success: res.success, job_id: res.job_id, message: res.message }
  }

  async listJobs(
    _status?: string,
    limit = 100,
    _offset = 0
  ): Promise<JobListResponse> {
    const res = await apiClient.listJobs()
    const jobs = res.jobs.map((j) => ({
      job_id: (j as { job_id?: string; status: string }).job_id ?? '',
      status: j.status as JobInfo['status'],
    }))
    return { jobs: jobs.slice(0, limit), total: jobs.length }
  }

  async getSystemHealth(): Promise<SystemHealthResponse> {
    const res = await apiClient.getSystemHealth()
    return { status: 'ok', ...res }
  }
}

export const jobApiClient = new JobApiClient()
