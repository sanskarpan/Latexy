/**
 * Typed REST API client for Latexy.
 * Handles job submission, state polling, result fetching, and PDF download.
 * All real-time updates come through the WebSocket (ws-client.ts).
 */

import { createTraceHeaders, trackBusinessEvent } from './telemetry'

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

// ------------------------------------------------------------------ //
//  Request / Response types                                           //
// ------------------------------------------------------------------ //

export type JobType =
  | 'latex_compilation'
  | 'llm_optimization'
  | 'combined'
  | 'ats_scoring'
  | 'cover_letter_generation'

export type OptimizationLevel = 'conservative' | 'balanced' | 'aggressive'

export type LatexCompiler = 'pdflatex' | 'xelatex' | 'lualatex'

export const ALLOWED_LATEXMK_FLAGS = [
  '--shell-escape',
  '--synctex=1',
  '--file-line-error',
  '--interaction=nonstopmode',
  '--halt-on-error',
] as const

export type LatexmkFlag = typeof ALLOWED_LATEXMK_FLAGS[number]

export interface CompileSettings {
  compiler?: LatexCompiler
  texlive_version?: string | null
  main_file?: string
  latexmk_flags?: LatexmkFlag[]
  extra_packages?: string[]
}

// ── Collaboration (Feature 40) ─────────────────────────────────────────────

export type CollabRole = 'editor' | 'commenter' | 'viewer'

export interface CollaboratorInfo {
  id: string
  resume_id: string
  user_id: string
  user_name: string | null
  user_email: string | null
  role: CollabRole
  invited_by: string | null
  joined_at: string | null
  created_at: string
}

export interface PresenceUser {
  name: string
  color: string
}

export interface JobSubmitRequest {
  job_type: JobType
  latex_content?: string
  job_description?: string
  optimization_level?: OptimizationLevel
  user_plan?: string
  device_fingerprint?: string
  industry?: string
  target_sections?: string[]
  custom_instructions?: string
  model?: string
  metadata?: Record<string, unknown>
  compiler?: LatexCompiler
  persona?: string
}

export interface OptimizationHistoryEntry {
  id: string
  created_at: string
  ats_score: number | null
  changes_count: number
  tokens_used: number | null
}

export interface BenchmarkResult {
  percentile: number | null
  sample_size: number
  cohort_median: number | null
  cohort_p25: number | null
  cohort_p75: number | null
  industry: string
  sufficient_data: boolean
  message?: string | null
}

export interface RecordOptimizationRequest {
  original_latex: string
  optimized_latex: string
  changes_made?: Array<{ section: string; change_type: string; reason: string }>
  ats_score?: number
  tokens_used?: number
  job_description?: string
}

export interface JobSubmitResponse {
  success: boolean
  job_id: string
  message: string
  estimated_time?: number
}

export interface JobStateResponse {
  job_id?: string
  job_type?: JobType
  status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'
  stage: string
  percent: number
  last_updated: number
  created_at?: number
  user_id?: string
}

export interface JobResultResponse {
  success: boolean
  job_id: string
  pdf_job_id?: string
  ats_score?: number
  ats_details?: {
    category_scores: Record<string, number>
    recommendations: string[]
    strengths: string[]
    warnings: string[]
  }
  changes_made?: Array<{
    section: string
    change_type: string
    reason: string
  }>
  compilation_time?: number
  optimization_time?: number
  tokens_used?: number
  error?: string
}

export interface TrialStatusResponse {
  usageCount: number
  remainingUses: number
  blocked: boolean
  canUse: boolean
  lastUsed: string | null
}

export interface HealthResponse {
  status: string
  version: string
  latex_available: boolean
}

export interface BillingAvailability {
  featureEnabled: boolean
  mode: 'enabled' | 'disabled' | 'unconfigured'
  available: boolean
  reason: string | null
  message: string
}

export interface CurrentSubscriptionResponse {
  userId: string
  planId: string
  planName: string
  status: string
  features: {
    compilations: number | string
    optimizations: number | string
    historyRetention: number
    prioritySupport: boolean
    apiAccess: boolean
    customModels?: boolean
  }
  subscriptionId?: string
  currentPeriodEnd?: string
}

export interface CouponValidationResponse {
  valid: boolean
  message: string
  discountPercent?: number | null
  code?: string | null
}

export interface SubscriptionCreateResponse {
  shortUrl?: string
  subscriptionId?: string
  customerId?: string
  message?: string
  verificationRequired?: boolean
  verificationPreviewUrl?: string | null
  coupon?: {
    code: string
    discount_percent: number
    message: string
  } | null
}

export interface DeveloperKey {
  id: string
  name: string
  key_prefix: string
  last_used_at: string | null
  request_count: number
  is_active: boolean
  scopes: string[]
  created_at: string
}

export interface DeveloperKeyCreateResponse extends DeveloperKey {
  full_key: string
}

export interface DeveloperUsagePoint {
  date: string
  count: number
}

export interface DeveloperUsageResponse {
  plan_id: string
  daily_limit: number
  history: DeveloperUsagePoint[]
}

export interface TeamSeat {
  id: string
  member_email: string
  member_user_id?: string | null
  status: string
  invited_at: string
  joined_at?: string | null
}

export interface TeamInviteResponse extends TeamSeat {
  invite_preview_url?: string | null
  message: string
}

export interface ResumeBase {
  title: string
  latex_content: string
  is_template?: boolean
  tags?: string[]
}

export interface ResumeResponse extends ResumeBase {
  id: string
  user_id: string
  parent_resume_id?: string | null
  variant_count?: number
  metadata?: { compiler?: string; custom_flags?: string; pinned?: boolean; [key: string]: unknown } | null
  share_token?: string | null
  share_url?: string | null
  // GitHub sync (Feature 37)
  github_sync_enabled?: boolean
  github_repo_name?: string | null
  github_last_sync_at?: string | null
  // Dropbox sync (Feature 77)
  dropbox_sync_enabled?: boolean
  dropbox_folder_path?: string | null
  dropbox_last_sync_at?: string | null
  created_at: string
  updated_at: string
  // Archive / Pin / Tags (Feature 39)
  archived_at?: string | null
  pinned?: boolean
  // Freshness (Feature 48) — computed server-side from updated_at
  days_since_updated?: number
  freshness_status?: 'fresh' | 'stale' | 'very_stale'
  // Feature 86 — presentation support
  document_type?: string
}

export interface DiffWithParentResponse {
  parent_latex: string
  parent_title: string
  variant_latex: string
  variant_title: string
}

export interface ResumeCreate extends ResumeBase {
  document_type?: string
}

export interface ResumeUpdate {
  title?: string
  latex_content?: string
  is_template?: boolean
  tags?: string[]
  document_type?: string
}

export interface ResumeStats {
  total_resumes: number
  total_templates: number
  last_updated: string | null
  avg_ats_score: number | null
  best_ats_score: number | null
  optimized_count: number
}

export interface AcademicCVReport {
  is_academic_cv: boolean
  detected_sections: string[]
  estimated_pages: number
  confidence: number
  reasons: string[]
}

export interface AcademicCVConvertRequest {
  target_industry: 'tech' | 'data_science' | 'finance' | 'consulting' | 'product' | 'other'
  target_role_description?: string
  title?: string
  force?: boolean
}

export interface AcademicCVConvertResponse {
  success: boolean
  variant_resume_id: string
  job_id: string
  report: AcademicCVReport
}

export interface ScoreHistoryPoint {
  timestamp: string
  ats_score: number
  label: string | null
}

export interface PaginatedResumesResponse {
  resumes: ResumeResponse[]
  total: number
  page: number
  limit: number
  pages: number
}

export interface UserAnalyticsResponse {
  user_id: string
  period_days: number
  total_compilations: number
  successful_compilations: number
  success_rate: number
  total_optimizations: number
  avg_compilation_time: number
  feature_usage: Record<string, number>
  daily_activity: Record<string, number>
  most_active_day: string | null
}

export interface AnalyticsTimeseriesPoint {
  date: string
  events: number
  compile_events: number
  optimize_events: number
  feature_events: number
}

export interface CompilationTimeseriesPoint {
  date: string
  total: number
  completed: number
  failed: number
  cancelled: number
  avg_latency: number
}

export interface OptimizationTimeseriesPoint {
  date: string
  total: number
  avg_tokens: number
  avg_ats_score: number
}

export interface FeatureSeriesPoint {
  feature: string
  count: number
  last_used_at: string | null
}

export interface UserAnalyticsTimeseriesResponse {
  user_id: string
  period_days: number
  activity_series: AnalyticsTimeseriesPoint[]
  compilation_series: CompilationTimeseriesPoint[]
  optimization_series: OptimizationTimeseriesPoint[]
  feature_series: FeatureSeriesPoint[]
  status_distribution: Record<string, number>
}

// ------------------------------------------------------------------ //
//  API client class                                                   //
// ------------------------------------------------------------------ //

export interface UploadForConversionResponse {
  success: boolean
  job_id?: string
  format: string
  filename: string
  is_direct: boolean
  latex_content?: string
}

export interface ParsePreviewResponse {
  success: boolean
  format: string
  filename: string
  name: string | null
  email: string | null
  experience_count: number
  education_count: number
  skills: string[]
  has_summary: boolean
}

export interface SemanticMatchResult {
  resume_id: string
  resume_title: string
  similarity_score: number | null
  matched_keywords: string[]
  missing_keywords: string[]
  semantic_gaps: {
    technical_skills: string[]
    soft_skills: string[]
    domain_specific: string[]
    similarity_score: number
  }
  note?: string
}

export interface SearchMatch {
  line_number: number
  line_content: string
  context_before: string[]
  context_after: string[]
  highlight_start: number
  highlight_end: number
}

export interface ResumeSearchResult {
  resume_id: string
  resume_title: string
  updated_at: string
  matches: SearchMatch[]
}

export interface SearchResponse {
  results: ResumeSearchResult[]
  total_resumes_matched: number
  query: string
}

export interface ExplainErrorRequest {
  error_message: string
  surrounding_latex?: string
  error_line?: number
}

export interface SpellCheckIssue {
  line: number
  column_start: number
  column_end: number
  severity: 'spelling' | 'grammar' | 'style'
  message: string
  replacements: string[]
  rule_id: string
}

export interface SpellCheckResponse {
  issues: SpellCheckIssue[]
  cached: boolean
}

// GitHub Integration (Feature 37)
export interface GitHubStatusResponse {
  connected: boolean
  username: string | null
}

export interface GitHubResumeStatus {
  github_sync_enabled: boolean
  github_repo_name: string | null
  github_last_sync_at: string | null
}

export interface GitHubSyncResponse {
  success: boolean
  message: string
  commit_url: string | null
}

export interface GitHubPullResponse {
  success: boolean
  latex_content: string
}

// Dropbox Integration (Feature 77)
export interface DropboxStatusResponse {
  connected: boolean
  display_name: string | null
  account_id: string | null
}

export interface DropboxResumeStatus {
  dropbox_sync_enabled: boolean
  dropbox_folder_path: string | null
  dropbox_last_sync_at: string | null
}

export interface DropboxSyncResponse {
  success: boolean
  message: string
  file_path: string | null
}

export interface DropboxPullResponse {
  success: boolean
  latex_content: string
}

export interface ScrapeJobResponse {
  title: string | null
  company: string | null
  description: string | null
  location: string | null
  job_type: string | null
  salary: string | null
  posted_at: string | null
  url: string
  cached: boolean
  source: 'api' | 'json_ld' | 'html' | 'og_tags'
  error: string | null
}

export interface ShareLinkResponse {
  share_token: string
  share_url: string
  created_at: string
  anonymous: boolean
}

export interface SharedResumeResponse {
  resume_title: string
  share_token: string
  pdf_url: string
  compiled_at: string | null
  is_anonymous: boolean
  anonymous_processing: boolean
}

export interface DateOccurrence {
  line: number
  original: string
  standardized: string
}

export interface StandardizeDatesResponse {
  occurrences: DateOccurrence[]
  standardized_latex: string
}

// Feature 55 — Age Analysis
export interface AgeEntry {
  line: number
  company_or_institution: string
  start_year: number
  end_year: number | null
  years_ago: number
  is_old: boolean
  is_prestigious: boolean
  recommendation: string
}

export interface AgeAnalysisResponse {
  entries: AgeEntry[]
  has_old_entries: boolean
}

// Feature 64 — Contact Formatter
export interface ContactChange {
  line: number
  original: string
  normalized: string
  type: 'phone' | 'linkedin' | 'github' | 'email'
}

export interface ContactFormatResponse {
  changes: ContactChange[]
  formatted_latex: string
}

// Feature 70 — Reference Page Generator
export interface ReferenceContact {
  name: string
  title: string
  company: string
  email?: string
  phone?: string
  relationship: string
}

export interface GenerateReferencesResponse {
  latex_content: string
}

// Feature 45 — Salary Estimator
export interface SalaryEstimateRequest {
  resume_latex: string
  target_role: string
  location: string
}

export interface SalaryEstimateResponse {
  currency: string
  low: number
  median: number
  high: number
  percentile: number
  key_skills: string[]
  disclaimer: string
  cached: boolean
}

export interface ExplainErrorResponse {
  success: boolean
  explanation: string
  suggested_fix: string
  corrected_code: string | null
  source: 'pattern' | 'llm' | 'error'
  cached: boolean
  processing_time: number
}

export interface SummaryVariant {
  emphasis: string
  title: string
  text: string
}

export interface GenerateSummaryRequest {
  resume_latex: string
  target_role?: string
  job_description?: string
  count?: number
}

export interface GenerateSummaryResponse {
  summaries: SummaryVariant[]
  cached: boolean
}

export interface ProofreadIssue {
  line: number
  column_start: number
  column_end: number
  category: 'weak_verb' | 'passive_voice' | 'buzzword' | 'vague' | string
  severity: 'error' | 'warning' | 'info'
  message: string
  suggestion: string | null
  original_text: string
  suggested_text: string | null
}

export interface ProofreadResponse {
  issues: ProofreadIssue[]
  summary: Record<string, number>
  overall_score: number
}

export interface GenerateBulletsRequest {
  job_title: string
  responsibility: string
  context?: string
  tone?: 'technical' | 'leadership' | 'analytical' | 'creative'
  count?: number
}

export interface GenerateBulletsResponse {
  bullets: string[]
  cached: boolean
}

export type RewriteAction = 'improve' | 'shorten' | 'quantify' | 'power_verbs' | 'change_tone' | 'expand'

export interface RewriteRequest {
  selected_text: string
  action: RewriteAction
  context?: string
  tone?: string
}

export interface RewriteResponse {
  rewritten: string
  action: string
  cached: boolean
}

export interface QuickTailorRequest {
  job_description: string
  company_name?: string
  role_title?: string
}

export interface QuickTailorResponse {
  fork_id: string
  job_id: string
}

export interface ConfidenceScoreResponse {
  overall: number
  writing_quality: number
  completeness: number
  quantification: number
  formatting: number
  section_order: number
  grade: 'A' | 'B' | 'C' | 'D' | 'F'
  improvements: string[]
  cached: boolean
}

export interface BibTeXEntry {
  identifier: string
  bibtex: string | null
  cite_key: string
  title: string | null
  authors: string | null
  year: number | null
  source_type: 'doi' | 'arxiv' | 'orcid' | 'unknown' | null
  cached: boolean
  error: string | null
}

export interface FetchReferencesResponse {
  entries: BibTeXEntry[]
  total: number
  successful: number
  processing_time: number
}

class ApiClient {
  private authToken: string | null = null
  readonly baseUrl: string = API_BASE

  setAuthToken(token: string | null): void {
    this.authToken = token
  }

  getAuthToken(): string | null {
    return this.authToken
  }

  private headers(extra: Record<string, string> = {}): HeadersInit {
    const h: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(typeof window !== 'undefined' ? createTraceHeaders() : {}),
      ...extra,
    }
    const token =
      this.authToken ??
      (typeof window !== 'undefined'
        ? localStorage.getItem('auth_token')
        : null)
    if (token) h['Authorization'] = `Bearer ${token}`
    return h
  }

  private async request<T>(
    path: string,
    init: RequestInit = {}
  ): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { ...this.headers(), ...(init.headers as Record<string, string> ?? {}) },
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
    }
    if (res.status === 204) {
      return undefined as T
    }
    const responseHeaders = res.headers as
      | { get?: (name: string) => string | null }
      | Record<string, string>
      | undefined
    const contentType =
      (typeof responseHeaders?.get === 'function'
        ? responseHeaders.get('content-type')
        : responseHeaders?.['content-type'] ?? responseHeaders?.['Content-Type']) || ''
    if (contentType.includes('application/json') || (!contentType && typeof res.json === 'function')) {
      return res.json() as Promise<T>
    }
    return (await res.text()) as T
  }

  // ---------------------------------------------------------------- //
  //  Health                                                           //
  // ---------------------------------------------------------------- //

  async health(): Promise<HealthResponse> {
    return this.request<HealthResponse>('/health')
  }

  // ---------------------------------------------------------------- //
  //  Job submission                                                   //
  // ---------------------------------------------------------------- //

  async submitJob(req: JobSubmitRequest): Promise<JobSubmitResponse> {
    const response = await this.request<JobSubmitResponse>('/jobs/submit', {
      method: 'POST',
      body: JSON.stringify(req),
    })
    if (typeof window !== 'undefined') {
      trackBusinessEvent('job_submit', '/jobs/submit', { jobType: req.job_type })
    }
    return response
  }

  // ---------------------------------------------------------------- //
  //  Job state & result                                               //
  // ---------------------------------------------------------------- //

  async getJobState(jobId: string): Promise<JobStateResponse> {
    return this.request<JobStateResponse>(`/jobs/${encodeURIComponent(jobId)}/state`)
  }

  async getJobResult(jobId: string): Promise<JobResultResponse> {
    return this.request<JobResultResponse>(`/jobs/${encodeURIComponent(jobId)}/result`)
  }

  async listJobs(): Promise<{ jobs: JobStateResponse[] }> {
    return this.request<{ jobs: JobStateResponse[] }>('/jobs')
  }

  // ---------------------------------------------------------------- //
  //  Resumes (Workspace)                                             //
  // ---------------------------------------------------------------- //

  async listResumes(page: number = 1, limit: number = 20, archived = false): Promise<ResumeResponse[]> {
    const data = await this.request<PaginatedResumesResponse>(
      `/resumes/?page=${page}&limit=${limit}${archived ? '&archived=true' : ''}`
    )
    return data.resumes ?? []
  }

  async listResumesPaginated(page: number = 1, limit: number = 20): Promise<PaginatedResumesResponse> {
    return this.request<PaginatedResumesResponse>(
      `/resumes/?page=${page}&limit=${limit}`
    )
  }

  async updateResumeTags(resumeId: string, tags: string[]): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/tags`, {
      method: 'PATCH',
      body: JSON.stringify({ tags }),
    })
  }

  async pinResume(resumeId: string): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/pin`, {
      method: 'PATCH',
    })
  }

  async unpinResume(resumeId: string): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/unpin`, {
      method: 'PATCH',
    })
  }

  async archiveResume(resumeId: string): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/archive`, {
      method: 'PATCH',
    })
  }

  async unarchiveResume(resumeId: string): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/unarchive`, {
      method: 'PATCH',
    })
  }

  async getResume(resumeId: string): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}`)
  }

  async createResume(resume: ResumeCreate): Promise<ResumeResponse> {
    return this.request<ResumeResponse>('/resumes/', {
      method: 'POST',
      body: JSON.stringify(resume),
    })
  }

  async mergeResumes(
    resumeIds: string[],
    sectionChoices: Record<string, string>
  ): Promise<{ merged_latex: string; new_resume_id: string }> {
    return this.request<{ merged_latex: string; new_resume_id: string }>(
      '/resumes/merge',
      {
        method: 'POST',
        body: JSON.stringify({
          resume_ids: resumeIds,
          section_choices: sectionChoices,
        }),
      }
    )
  }

  async updateResume(
    resumeId: string,
    resume: ResumeUpdate
  ): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}`, {
      method: 'PUT',
      body: JSON.stringify(resume),
    })
  }

  async deleteResume(resumeId: string): Promise<void> {
    await fetch(`${API_BASE}/resumes/${encodeURIComponent(resumeId)}`, {
      method: 'DELETE',
      headers: this.headers(),
    })
  }

  async updateResumeSettings(
    resumeId: string,
    settings: CompileSettings & { custom_flags?: string; last_persona?: string }
  ): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/settings`, {
      method: 'PATCH',
      body: JSON.stringify(settings),
    })
  }

  async getResumeStats(): Promise<ResumeStats> {
    return this.request<ResumeStats>('/resumes/stats')
  }

  // ---------------------------------------------------------------- //
  //  Analytics                                                       //
  // ---------------------------------------------------------------- //

  async getMyAnalytics(days: number = 30): Promise<UserAnalyticsResponse> {
    return this.request<UserAnalyticsResponse>(`/analytics/me?days=${days}`)
  }

  async getMyAnalyticsTimeseries(days: number = 30): Promise<UserAnalyticsTimeseriesResponse> {
    return this.request<UserAnalyticsTimeseriesResponse>(`/analytics/me/timeseries?days=${days}`)
  }

  // ---------------------------------------------------------------- //
  //  Job cancellation                                                 //
  // ---------------------------------------------------------------- //

  async cancelJob(jobId: string): Promise<void> {
    await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`, {
      method: 'DELETE',
      headers: this.headers(),
    })
  }

  // ---------------------------------------------------------------- //
  //  PDF download                                                     //
  // ---------------------------------------------------------------- //

  getPdfUrl(jobId: string): string {
    return `${API_BASE}/download/${encodeURIComponent(jobId)}`
  }

  async downloadPdf(jobId: string): Promise<Blob> {
    const res = await fetch(this.getPdfUrl(jobId), {
      headers: this.headers({ 'Content-Type': '' }),
    })
    if (!res.ok) throw new Error(`PDF download failed: HTTP ${res.status}`)
    return res.blob()
  }

  async getPdfBlobUrl(jobId: string): Promise<string> {
    const blob = await this.downloadPdf(jobId)
    return URL.createObjectURL(blob)
  }

  // ---------------------------------------------------------------- //
  //  Trial system                                                     //
  // ---------------------------------------------------------------- //

  async getTrialStatus(fingerprint: string): Promise<TrialStatusResponse> {
    return this.request<TrialStatusResponse>(
      `/public/trial-status?fingerprint=${encodeURIComponent(fingerprint)}`
    )
  }

  async trackUsage(
    fingerprint: string,
    action: string,
    resourceType?: string,
    metadata?: Record<string, unknown>
  ): Promise<void> {
    await fetch(`${API_BASE}/public/track-usage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        deviceFingerprint: fingerprint,
        action,
        resourceType,
        metadata,
      }),
    })
  }

  // ---------------------------------------------------------------- //
  //  Convenience wrappers (for pages that submit directly)           //
  // ---------------------------------------------------------------- //

  async compileLatex(body: {
    latex_content: string
    device_fingerprint?: string
    user_plan?: string
    resume_id?: string
    compiler?: LatexCompiler
  }): Promise<JobSubmitResponse> {
    return this.submitJob({
      job_type: 'latex_compilation',
      latex_content: body.latex_content,
      device_fingerprint: body.device_fingerprint,
      user_plan: body.user_plan,
      metadata: body.resume_id ? { resume_id: body.resume_id } : undefined,
      compiler: body.compiler,
    })
  }

  async optimizeAndCompile(body: {
    latex_content: string
    job_description?: string
    optimization_level?: OptimizationLevel
    device_fingerprint?: string
    user_plan?: string
    target_sections?: string[]
    custom_instructions?: string
    model?: string
    resume_id?: string
    compiler?: LatexCompiler
    persona?: string
  }): Promise<JobSubmitResponse> {
    return this.submitJob({
      job_type: 'combined',
      latex_content: body.latex_content,
      job_description: body.job_description,
      optimization_level: body.optimization_level ?? 'balanced',
      device_fingerprint: body.device_fingerprint,
      user_plan: body.user_plan,
      target_sections: body.target_sections,
      custom_instructions: body.custom_instructions,
      model: body.model,
      metadata: body.resume_id ? { resume_id: body.resume_id } : undefined,
      compiler: body.compiler,
      persona: body.persona,
    })
  }

  async getPersonas(): Promise<Array<{ key: string; label: string; description: string }>> {
    return this.request('/ai/personas')
  }

  // ---------------------------------------------------------------- //
  //  Optimization history                                             //
  // ---------------------------------------------------------------- //

  async getOptimizationHistory(resumeId: string): Promise<OptimizationHistoryEntry[]> {
    return this.request<OptimizationHistoryEntry[]>(
      `/resumes/${encodeURIComponent(resumeId)}/optimization-history`
    )
  }

  async getScoreHistory(resumeId: string): Promise<ScoreHistoryPoint[]> {
    return this.request<ScoreHistoryPoint[]>(
      `/resumes/${encodeURIComponent(resumeId)}/score-history`
    )
  }

  async restoreOptimization(
    resumeId: string,
    optId: string
  ): Promise<{ success: boolean; latex_content: string }> {
    return this.request(`/resumes/${encodeURIComponent(resumeId)}/restore-optimization/${encodeURIComponent(optId)}`, {
      method: 'POST',
    })
  }

  async recordOptimization(
    resumeId: string,
    data: RecordOptimizationRequest
  ): Promise<{ success: boolean; id: string }> {
    return this.request(`/resumes/${encodeURIComponent(resumeId)}/record-optimization`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async scoreResume(body: {
    latex_content: string
    job_description?: string
    industry?: string
  }): Promise<JobSubmitResponse> {
    return this.submitJob({
      job_type: 'ats_scoring',
      latex_content: body.latex_content,
      job_description: body.job_description,
      industry: body.industry,
    })
  }

  // ---------------------------------------------------------------- //
  //  System health (for job queue display)                           //
  // ---------------------------------------------------------------- //

  async getSystemHealth(): Promise<{
    queue_depths: Record<string, number>
    worker_count: number
  }> {
    return this.request('/jobs/health')
  }

  // ---------------------------------------------------------------- //
  //  Subscription / billing (used by billing/page.tsx)              //
  // ---------------------------------------------------------------- //

  /** Returns the current user's plan ID (e.g. "free", "pro", "byok"). */
  async getCurrentPlan(): Promise<string> {
    try {
      const data = await this.request<CurrentSubscriptionResponse>('/subscription/current')
      return data.planId ?? 'free'
    } catch {
      return 'free'
    }
  }

  async getCurrentSubscription(): Promise<{
    success: boolean
    data?: CurrentSubscriptionResponse
    error?: string
  }> {
    try {
      const data = await this.request<CurrentSubscriptionResponse>('/subscription/current')
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async getSubscriptionPlans(): Promise<{
    success: boolean
    data?: { plans: Record<string, unknown>; billing: BillingAvailability }
    error?: string
  }> {
    try {
      const data = await this.request<{
        plans: Record<string, unknown>
        billing: {
          feature_enabled: boolean
          mode: 'enabled' | 'disabled' | 'unconfigured'
          available: boolean
          reason?: string | null
          message: string
        }
      }>('/subscription/plans')
      return {
        success: true,
        data: {
          plans: data.plans,
          billing: {
            featureEnabled: data.billing.feature_enabled,
            mode: data.billing.mode,
            available: data.billing.available,
            reason: data.billing.reason ?? null,
            message: data.billing.message,
          },
        },
      }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async createSubscription(
    planId: string,
    email: string,
    name: string,
    options?: {
      billingPeriod?: 'monthly' | 'annual'
      couponCode?: string
      studentEmail?: string
    }
  ): Promise<{
    success: boolean
    data?: SubscriptionCreateResponse
    error?: string
  }> {
    try {
      const data = await this.request<SubscriptionCreateResponse>(
        '/subscription/create',
        {
          method: 'POST',
          body: JSON.stringify({
            planId,
            customerEmail: email,
            customerName: name,
            billingPeriod: options?.billingPeriod ?? 'monthly',
            couponCode: options?.couponCode ?? null,
            studentEmail: options?.studentEmail ?? null,
          }),
        }
      )
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async cancelSubscription(): Promise<{
    success: boolean
    message?: string
    error?: string
  }> {
    try {
      const data = await this.request<{ success: boolean; message?: string; error?: string }>(
        '/subscription/cancel',
        { method: 'POST' }
      )
      return data
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async validateCoupon(
    code: string,
    planId: string,
    billingPeriod: 'monthly' | 'annual' = 'monthly',
  ): Promise<{
    success: boolean
    data?: CouponValidationResponse
    error?: string
  }> {
    try {
      const data = await this.request<CouponValidationResponse>('/billing/validate-coupon', {
        method: 'POST',
        body: JSON.stringify({ code, planId, billingPeriod }),
      })
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async verifyStudentSubscription(token: string): Promise<{
    success: boolean
    data?: { success: boolean; message: string }
    error?: string
  }> {
    try {
      const data = await this.request<{ success: boolean; message: string }>(`/subscription/student/verify/${encodeURIComponent(token)}`)
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async getDeveloperKeys(): Promise<{ success: boolean; data?: DeveloperKey[]; error?: string }> {
    try {
      const data = await this.request<DeveloperKey[]>('/developer/keys')
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async getDeveloperUsage(): Promise<{ success: boolean; data?: DeveloperUsageResponse; error?: string }> {
    try {
      const data = await this.request<DeveloperUsageResponse>('/developer/usage')
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async createDeveloperKey(
    name: string,
    scopes?: string[],
  ): Promise<{ success: boolean; data?: DeveloperKeyCreateResponse; error?: string }> {
    try {
      const data = await this.request<DeveloperKeyCreateResponse>('/developer/keys', {
        method: 'POST',
        body: JSON.stringify({ name, scopes }),
      })
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async renameDeveloperKey(
    keyId: string,
    name: string,
  ): Promise<{ success: boolean; data?: DeveloperKey; error?: string }> {
    try {
      const data = await this.request<DeveloperKey>(`/developer/keys/${encodeURIComponent(keyId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ name }),
      })
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async revokeDeveloperKey(keyId: string): Promise<{ success: boolean; error?: string }> {
    try {
      await this.request(`/developer/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' })
      return { success: true }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async getTeamSeats(): Promise<{ success: boolean; data?: TeamSeat[]; error?: string }> {
    try {
      const data = await this.request<TeamSeat[]>('/team/seats')
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async inviteTeamSeat(email: string): Promise<{ success: boolean; data?: TeamInviteResponse; error?: string }> {
    try {
      const data = await this.request<TeamInviteResponse>('/team/invite', {
        method: 'POST',
        body: JSON.stringify({ email }),
      })
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async removeTeamSeat(seatId: string): Promise<{ success: boolean; error?: string }> {
    try {
      await this.request(`/team/seats/${encodeURIComponent(seatId)}`, { method: 'DELETE' })
      return { success: true }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async joinTeamSeat(token: string): Promise<{
    success: boolean
    data?: { success: boolean; message: string }
    error?: string
  }> {
    try {
      const data = await this.request<{ success: boolean; message: string }>(`/team/join/${encodeURIComponent(token)}`)
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  // ---------------------------------------------------------------- //
  //  ATS analysis endpoints                                          //
  // ---------------------------------------------------------------- //

  async analyzeJobDescription(body: {
    job_description: string
    user_plan?: string
    async_processing?: boolean
  }): Promise<{
    success: boolean
    job_id?: string
    keywords?: string[]
    requirements?: string[]
    preferred_qualifications?: string[]
    detected_industry?: string
    analysis_metrics?: Record<string, unknown>
    optimization_tips?: string[]
    processing_time?: number
    message: string
  }> {
    return this.request('/ats/analyze-job-description', {
      method: 'POST',
      body: JSON.stringify({ async_processing: true, ...body }),
    })
  }

  async getAtsRecommendations(body: {
    ats_score: number
    category_scores: Record<string, number>
    industry?: string
  }): Promise<{
    success: boolean
    priority_improvements: Array<{
      category: string
      current_score: number
      priority: string
      potential_improvement: number
      recommended_actions: string[]
    }>
    quick_wins: string[]
    long_term_improvements: string[]
    industry_specific_tips: string[]
    estimated_score_improvement: number
    message: string
  }> {
    return this.request('/ats/recommendations', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async getIndustryKeywords(industry: string): Promise<{
    success: boolean
    industry: string
    keywords: string[]
    count: number
    message: string
  }> {
    return this.request(`/ats/industry-keywords/${encodeURIComponent(industry)}`)
  }

  async getSupportedIndustries(): Promise<{
    success: boolean
    industries: string[]
    count: number
    message: string
  }> {
    return this.request('/ats/supported-industries')
  }

  async getIndustryProfiles(): Promise<{
    success: boolean
    profiles: Array<{ key: string; label: string }>
  }> {
    return this.request('/ats/industry-profiles')
  }

  async deepAnalyzeResume(body: {
    latex_content: string
    job_description?: string
    device_fingerprint?: string
    industry_override?: string
  }): Promise<{
    success: boolean
    job_id?: string
    uses_remaining?: number | null
    message: string
  }> {
    return this.request('/ats/deep-analyze', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async semanticMatch(body: {
    job_description: string
    resume_ids?: string[]
  }): Promise<{
    success: boolean
    results: SemanticMatchResult[]
    message: string
  }> {
    return this.request('/ats/semantic-match', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async quickScoreATS(
    latexContent: string,
    jobDescription?: string,
  ): Promise<QuickScoreResponse> {
    return this.request<QuickScoreResponse>('/ats/quick-score', {
      method: 'POST',
      body: JSON.stringify({
        latex_content: latexContent,
        job_description: jobDescription ?? null,
      }),
    })
  }

  async getAtsSimulatorProfiles(): Promise<{
    profiles: Array<{ key: string; label: string; tier: string }>
  }> {
    return this.request('/ats/simulate/profiles')
  }

  async simulateAts(body: {
    latex_content: string
    ats_name: string
  }): Promise<{
    ats_label: string
    plain_text_view: string
    issues: Array<{
      type: string
      severity: string
      description: string
      line_range: string
    }>
    score: number
    recommendations: string[]
    cached: boolean
  }> {
    return this.request('/ats/simulate', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async keywordDensity(body: {
    resume_latex: string
    job_description: string
  }): Promise<{
    keywords: Array<{
      keyword: string
      status: 'present' | 'partial' | 'missing'
      count: number
      required: boolean
      suggested_location: string | null
    }>
    coverage_score: number
  }> {
    return this.request('/ats/keyword-density', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // ---------------------------------------------------------------- //
  //  Publications (Feature 58)                                       //
  // ---------------------------------------------------------------- //

  async generatePublications(body: GeneratePublicationsRequest): Promise<GeneratePublicationsResponse> {
    return this.request('/ai/generate-publications', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // ---------------------------------------------------------------- //
  //  Multi-format file I/O                                           //
  // ---------------------------------------------------------------- //

  private getAuthHeader(): Record<string, string> {
    const token =
      this.authToken ??
      (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null)
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  // Upload a file for conversion to LaTeX
  async uploadForConversion(
    file: File,
    sourceHint?: string,
    sourcePlatform?: string,
  ): Promise<UploadForConversionResponse> {
    const formData = new FormData()
    formData.append('file', file)
    if (sourceHint) formData.append('source_hint', sourceHint)
    const url = new URL(`${this.baseUrl}/formats/upload`)
    if (sourcePlatform) url.searchParams.set('source_platform', sourcePlatform)
    const response = await fetch(url.toString(), {
      method: 'POST',
      headers: this.getAuthHeader(),
      body: formData,
    })
    if (!response.ok) {
      const error = await response.text()
      throw new Error(error || `Upload failed: ${response.status}`)
    }
    return response.json()
  }

  // Parse a file and return basic preview data (no LLM conversion)
  async parseForPreview(file: File): Promise<ParsePreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(`${this.baseUrl}/formats/parse`, {
      method: 'POST',
      headers: this.getAuthHeader(),
      body: formData,
    })
    if (!response.ok) {
      const error = await response.text()
      throw new Error(error || `Parse failed: ${response.status}`)
    }
    return response.json()
  }

  // Export a saved resume in a specific format (returns Blob for download)
  async exportResume(resumeId: string, format: string): Promise<Blob> {
    const response = await fetch(`${this.baseUrl}/export/${resumeId}/${format}`, {
      headers: this.getAuthHeader(),
    })
    if (!response.ok) {
      throw new Error(`Export failed: ${response.status}`)
    }
    return response.blob()
  }

  // ---------------------------------------------------------------- //
  //  Checkpoints / version history                                    //
  // ---------------------------------------------------------------- //

  async createCheckpoint(
    resumeId: string,
    label: string
  ): Promise<{ id: string; created_at: string; label: string }> {
    return this.request(`/resumes/${encodeURIComponent(resumeId)}/checkpoints`, {
      method: 'POST',
      body: JSON.stringify({ label }),
    })
  }

  async listCheckpoints(
    resumeId: string,
    limit: number = 50,
    offset: number = 0
  ): Promise<CheckpointEntry[]> {
    return this.request<CheckpointEntry[]>(
      `/resumes/${encodeURIComponent(resumeId)}/checkpoints?limit=${limit}&offset=${offset}`
    )
  }

  async getCheckpointContent(
    resumeId: string,
    checkpointId: string
  ): Promise<CheckpointContentResponse> {
    return this.request<CheckpointContentResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/checkpoints/${encodeURIComponent(checkpointId)}/content`
    )
  }

  async deleteCheckpoint(resumeId: string, checkpointId: string): Promise<void> {
    const res = await fetch(
      `${API_BASE}/resumes/${encodeURIComponent(resumeId)}/checkpoints/${encodeURIComponent(checkpointId)}`,
      { method: 'DELETE', headers: this.headers() }
    )
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || `Delete failed (${res.status})`)
    }
  }

  // ---------------------------------------------------------------- //
  //  Resume variants / fork                                           //
  // ---------------------------------------------------------------- //

  async forkResume(resumeId: string, title?: string): Promise<ResumeResponse> {
    return this.request<ResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/fork`, {
      method: 'POST',
      body: JSON.stringify({ title: title || null }),
    })
  }

  async getResumeVariants(resumeId: string): Promise<ResumeResponse[]> {
    return this.request<ResumeResponse[]>(`/resumes/${encodeURIComponent(resumeId)}/variants`)
  }

  async getResumeDiffWithParent(resumeId: string): Promise<DiffWithParentResponse> {
    return this.request<DiffWithParentResponse>(`/resumes/${encodeURIComponent(resumeId)}/diff-with-parent`)
  }

  async getAcademicCVReport(resumeId: string): Promise<AcademicCVReport> {
    return this.request<AcademicCVReport>(`/resumes/${encodeURIComponent(resumeId)}/academic-cv-report`)
  }

  async convertAcademicCV(
    resumeId: string,
    body: AcademicCVConvertRequest,
  ): Promise<AcademicCVConvertResponse> {
    return this.request<AcademicCVConvertResponse>(`/resumes/${encodeURIComponent(resumeId)}/academic-cv-convert`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // Export raw LaTeX content in a specific format (for /try page, no auth needed)
  async exportContent(latexContent: string, format: string): Promise<Blob> {
    const response = await fetch(`${this.baseUrl}/export/content/${format}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeader(),
      },
      body: JSON.stringify({ latex_content: latexContent }),
    })
    if (!response.ok) {
      throw new Error(`Export failed: ${response.status}`)
    }
    return response.blob()
  }

  // ---------------------------------------------------------------- //
  //  Templates                                                       //
  // ---------------------------------------------------------------- //

  async getTemplates(category?: string, search?: string): Promise<TemplateResponse[]> {
    const params = new URLSearchParams()
    if (category && category !== 'all') params.set('category', category)
    if (search) params.set('search', search)
    const qs = params.toString()
    return this.request<TemplateResponse[]>(`/templates/${qs ? `?${qs}` : ''}`)
  }

  async getTemplateCategories(): Promise<TemplateCategoryCount[]> {
    return this.request<TemplateCategoryCount[]>('/templates/categories')
  }

  async getTemplate(id: string): Promise<TemplateDetailResponse> {
    return this.request<TemplateDetailResponse>(`/templates/${encodeURIComponent(id)}`)
  }

  async useTemplate(id: string, title?: string): Promise<{ resume_id: string; title: string }> {
    return this.request<{ resume_id: string; title: string }>(
      `/templates/${encodeURIComponent(id)}/use`,
      { method: 'POST', body: JSON.stringify({ title: title || null }) }
    )
  }

  // ---------------------------------------------------------------- //
  //  Cover letters                                                    //
  // ---------------------------------------------------------------- //

  async listCoverLetters(
    page: number = 1,
    limit: number = 20,
    search: string = ''
  ): Promise<PaginatedCoverLettersResponse> {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) })
    if (search) params.set('search', search)
    return this.request<PaginatedCoverLettersResponse>(
      `/cover-letters/?${params.toString()}`
    )
  }

  async getCoverLetterStats(): Promise<CoverLetterStatsResponse> {
    return this.request<CoverLetterStatsResponse>('/cover-letters/stats')
  }

  async generateCoverLetter(
    params: GenerateCoverLetterRequest
  ): Promise<GenerateCoverLetterResponse> {
    return this.request<GenerateCoverLetterResponse>('/cover-letters/generate', {
      method: 'POST',
      body: JSON.stringify(params),
    })
  }

  async getCoverLetter(id: string): Promise<CoverLetterResponse> {
    return this.request<CoverLetterResponse>(
      `/cover-letters/${encodeURIComponent(id)}`
    )
  }

  async updateCoverLetter(
    id: string,
    latexContent: string
  ): Promise<CoverLetterResponse> {
    return this.request<CoverLetterResponse>(
      `/cover-letters/${encodeURIComponent(id)}`,
      { method: 'PUT', body: JSON.stringify({ latex_content: latexContent }) }
    )
  }

  async deleteCoverLetter(id: string): Promise<void> {
    await fetch(`${API_BASE}/cover-letters/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: this.headers(),
    })
  }

  async getResumeCoverLetters(resumeId: string): Promise<CoverLetterResponse[]> {
    return this.request<CoverLetterResponse[]>(
      `/cover-letters/resume/${encodeURIComponent(resumeId)}`
    )
  }

  // ── Analytics tracking ────────────────────────────────────────────

  async trackEvent(eventType: string, metadata?: Record<string, unknown>): Promise<void> {
    try {
      await this.request<{ message: string }>('/analytics/track', {
        method: 'POST',
        body: JSON.stringify({ event_type: eventType, metadata }),
      })
    } catch {
      // Non-critical — don't disrupt user flow
    }
  }

  async trackCompilation(compilationId: string, compilationStatus: string, compilationTime?: number): Promise<void> {
    try {
      const params = new URLSearchParams({ compilation_id: compilationId, status: compilationStatus })
      if (compilationTime != null) params.set('compilation_time', String(compilationTime))
      await this.request<{ message: string }>(`/analytics/track/compilation?${params.toString()}`, {
        method: 'POST',
      })
    } catch {
      // Non-critical
    }
  }

  async trackOptimization(optimizationId: string, provider: string, model: string, tokensUsed?: number): Promise<void> {
    try {
      const params = new URLSearchParams({ optimization_id: optimizationId, provider, model })
      if (tokensUsed != null) params.set('tokens_used', String(tokensUsed))
      await this.request<{ message: string }>(`/analytics/track/optimization?${params.toString()}`, {
        method: 'POST',
      })
    } catch {
      // Non-critical
    }
  }

  async trackFeatureUsage(feature: string): Promise<void> {
    try {
      const params = new URLSearchParams({ feature })
      await this.request<{ message: string }>(`/analytics/track/feature-usage?${params.toString()}`, {
        method: 'POST',
      })
    } catch {
      // Non-critical
    }
  }

  // ---------------------------------------------------------------- //
  //  AI error explainer                                               //
  // ---------------------------------------------------------------- //

  async explainLatexError(body: ExplainErrorRequest): Promise<ExplainErrorResponse> {
    return this.request<ExplainErrorResponse>('/ai/explain-error', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async checkSpelling(latexContent: string, language = 'en-US'): Promise<SpellCheckResponse> {
    return this.request<SpellCheckResponse>('/ai/spell-check', {
      method: 'POST',
      body: JSON.stringify({ latex_content: latexContent, language }),
    })
  }

  async generateBullets(body: GenerateBulletsRequest): Promise<GenerateBulletsResponse> {
    return this.request<GenerateBulletsResponse>('/ai/generate-bullets', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async generateSummary(body: GenerateSummaryRequest): Promise<GenerateSummaryResponse> {
    return this.request<GenerateSummaryResponse>('/ai/generate-summary', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async proofreadResume(latexContent: string): Promise<ProofreadResponse> {
    return this.request<ProofreadResponse>('/ai/proofread', {
      method: 'POST',
      body: JSON.stringify({ latex_content: latexContent }),
    })
  }

  async confidenceScore(latexContent: string): Promise<ConfidenceScoreResponse> {
    return this.request<ConfidenceScoreResponse>('/ai/confidence-score', {
      method: 'POST',
      body: JSON.stringify({ latex_content: latexContent }),
    })
  }

  async rewriteText(body: RewriteRequest): Promise<RewriteResponse> {
    return this.request<RewriteResponse>('/ai/rewrite', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async quickTailorResume(resumeId: string, body: QuickTailorRequest): Promise<QuickTailorResponse> {
    return this.request<QuickTailorResponse>(`/resumes/${resumeId}/quick-tailor`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // ---------------------------------------------------------------- //
  //  References (BibTeX import)                                      //
  // ---------------------------------------------------------------- //

  async fetchReferences(identifiers: string[]): Promise<FetchReferencesResponse> {
    return this.request<FetchReferencesResponse>('/references/fetch', {
      method: 'POST',
      body: JSON.stringify({ identifiers }),
    })
  }

  async fetchOrcidPublications(orcidId: string, maxResults = 20): Promise<FetchReferencesResponse> {
    return this.request<FetchReferencesResponse>('/references/fetch-orcid', {
      method: 'POST',
      body: JSON.stringify({ orcid_id: orcidId, max_results: maxResults }),
    })
  }

  async searchResumes(query: string, limit = 20): Promise<SearchResponse> {
    const params = new URLSearchParams({ q: query, limit: String(limit) })
    return this.request<SearchResponse>(`/resumes/search?${params.toString()}`)
  }

  // ---------------------------------------------------------------- //
  //  Share links                                                       //
  // ---------------------------------------------------------------- //

  async createShareLink(resumeId: string, anonymous = false): Promise<ShareLinkResponse> {
    return this.request<ShareLinkResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/share`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anonymous }),
      }
    )
  }

  async revokeShareLink(resumeId: string): Promise<void> {
    const res = await fetch(
      `${API_BASE}/resumes/${encodeURIComponent(resumeId)}/share`,
      { method: 'DELETE', headers: this.headers() }
    )
    if (!res.ok && res.status !== 204) {
      const body = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
    }
  }

  async getSharedResume(shareToken: string): Promise<SharedResumeResponse> {
    return this.request<SharedResumeResponse>(`/share/${encodeURIComponent(shareToken)}`)
  }

  // ---------------------------------------------------------------- //
  //  Bulk export (Feature 49)                                         //
  // ---------------------------------------------------------------- //

  async bulkExport(format: 'tex' | 'pdf' | 'docx'): Promise<Blob> {
    const res = await fetch(
      `${API_BASE}/resumes/export/bulk?format=${format}`,
      { headers: this.headers() }
    )
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
    }
    return res.blob()
  }

  // ---------------------------------------------------------------- //
  //  Date standardizer (Feature 57)                                   //
  // ---------------------------------------------------------------- //

  async standardizeDates(
    latex_content: string,
    target_format: 'MMM YYYY' | 'MMMM YYYY' | 'YYYY-MM' | 'MM/YYYY'
  ): Promise<StandardizeDatesResponse> {
    return this.request<StandardizeDatesResponse>('/ai/standardize-dates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latex_content, target_format }),
    })
  }

  // ---------------------------------------------------------------- //
  //  Feature flags                                                    //
  // ---------------------------------------------------------------- //

  async getAdminFeatureFlags(): Promise<Array<{
    key: string
    enabled: boolean
    label: string
    description: string | null
    updated_at: string | null
  }>> {
    return this.request('/admin/feature-flags')
  }

  async updateFeatureFlag(key: string, enabled: boolean): Promise<{
    key: string
    enabled: boolean
    label: string
    description: string | null
    updated_at: string | null
  }> {
    return this.request(`/admin/feature-flags/${encodeURIComponent(key)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    })
  }

  // ---------------------------------------------------------------- //
  //  Job Application Tracker                                          //
  // ---------------------------------------------------------------- //

  async createApplication(body: CreateApplicationRequest): Promise<JobApplication> {
    return this.request<JobApplication>('/tracker/applications', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async listApplications(statusFilter?: string): Promise<TrackerListResponse> {
    const params = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : ''
    return this.request<TrackerListResponse>(`/tracker/applications${params}`)
  }

  async getApplication(id: string): Promise<JobApplication> {
    return this.request<JobApplication>(`/tracker/applications/${encodeURIComponent(id)}`)
  }

  async updateApplication(id: string, body: Partial<CreateApplicationRequest>): Promise<JobApplication> {
    return this.request<JobApplication>(`/tracker/applications/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    })
  }

  async deleteApplication(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/tracker/applications/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: this.headers(),
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
    }
  }

  async updateApplicationStatus(id: string, status: string): Promise<JobApplication> {
    return this.request<JobApplication>(`/tracker/applications/${encodeURIComponent(id)}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    })
  }

  async getTrackerStats(): Promise<TrackerStats> {
    return this.request<TrackerStats>('/tracker/stats')
  }

  // ---------------------------------------------------------------- //
  //  Interview Prep                                                  //
  // ---------------------------------------------------------------- //

  async generateInterviewPrep(body: GenerateInterviewPrepRequest): Promise<GenerateInterviewPrepApiResponse> {
    return this.request<GenerateInterviewPrepApiResponse>('/interview-prep/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async getInterviewPrep(prepId: string): Promise<InterviewPrepResponse> {
    return this.request<InterviewPrepResponse>(`/interview-prep/${encodeURIComponent(prepId)}`)
  }

  async listInterviewPrep(resumeId: string): Promise<InterviewPrepResponse[]> {
    return this.request<InterviewPrepResponse[]>(`/resumes/${encodeURIComponent(resumeId)}/interview-prep`)
  }

  async deleteInterviewPrep(prepId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/interview-prep/${encodeURIComponent(prepId)}`, {
      method: 'DELETE',
      headers: this.headers(),
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
    }
  }

  // ---------------------------------------------------------------- //
  //  Notification preferences (Feature 19)                           //
  // ---------------------------------------------------------------- //

  async getNotificationPrefs(): Promise<NotificationPrefs> {
    return this.request<NotificationPrefs>('/settings/notifications')
  }

  async updateNotificationPrefs(prefs: NotificationPrefs): Promise<NotificationPrefs> {
    return this.request<NotificationPrefs>('/settings/notifications', {
      method: 'PUT',
      body: JSON.stringify(prefs),
    })
  }

  // ---------------------------------------------------------------- //
  //  Job Board URL Scraper (Feature 33)                              //
  // ---------------------------------------------------------------- //

  async scrapeJobDescription(url: string): Promise<ScrapeJobResponse> {
    return this.request<ScrapeJobResponse>('/scrape-job-description', {
      method: 'POST',
      body: JSON.stringify({ url }),
    })
  }

  // ---------------------------------------------------------------- //
  //  GitHub Integration (Feature 37)                                  //
  // ---------------------------------------------------------------- //

  async getGitHubStatus(): Promise<GitHubStatusResponse> {
    return this.request<GitHubStatusResponse>('/github/status')
  }

  async disconnectGitHub(): Promise<{ success: boolean; message: string }> {
    return this.request('/github/disconnect', { method: 'DELETE' })
  }

  async getResumeGitHubStatus(resumeId: string): Promise<GitHubResumeStatus> {
    return this.request<GitHubResumeStatus>(`/github/resumes/${encodeURIComponent(resumeId)}/status`)
  }

  async enableGitHubSync(resumeId: string, repoName = 'latexy-resumes'): Promise<GitHubResumeStatus> {
    return this.request<GitHubResumeStatus>(`/github/resumes/${encodeURIComponent(resumeId)}/enable`, {
      method: 'POST',
      body: JSON.stringify({ repo_name: repoName }),
    })
  }

  async disableGitHubSync(resumeId: string): Promise<GitHubResumeStatus> {
    return this.request<GitHubResumeStatus>(`/github/resumes/${encodeURIComponent(resumeId)}/disable`, {
      method: 'POST',
    })
  }

  async pushToGitHub(resumeId: string): Promise<GitHubSyncResponse> {
    return this.request<GitHubSyncResponse>(`/github/resumes/${encodeURIComponent(resumeId)}/push`, {
      method: 'POST',
    })
  }

  async pullFromGitHub(resumeId: string): Promise<GitHubPullResponse> {
    return this.request<GitHubPullResponse>(`/github/resumes/${encodeURIComponent(resumeId)}/pull`, {
      method: 'POST',
    })
  }

  // ---------------------------------------------------------------- //
  //  Dropbox Integration (Feature 77)                               //
  // ---------------------------------------------------------------- //

  async getDropboxStatus(): Promise<DropboxStatusResponse> {
    return this.request<DropboxStatusResponse>('/dropbox/status')
  }

  async disconnectDropbox(): Promise<{ success: boolean; message: string }> {
    return this.request('/dropbox/disconnect', { method: 'DELETE' })
  }

  async getResumeDropboxStatus(resumeId: string): Promise<DropboxResumeStatus> {
    return this.request<DropboxResumeStatus>(`/dropbox/resumes/${encodeURIComponent(resumeId)}/status`)
  }

  async enableDropboxSync(resumeId: string): Promise<DropboxResumeStatus> {
    return this.request<DropboxResumeStatus>(`/dropbox/resumes/${encodeURIComponent(resumeId)}/enable`, {
      method: 'POST',
    })
  }

  async disableDropboxSync(resumeId: string): Promise<DropboxResumeStatus> {
    return this.request<DropboxResumeStatus>(`/dropbox/resumes/${encodeURIComponent(resumeId)}/disable`, {
      method: 'POST',
    })
  }

  async pushToDropbox(resumeId: string): Promise<DropboxSyncResponse> {
    return this.request<DropboxSyncResponse>(`/dropbox/resumes/${encodeURIComponent(resumeId)}/push`, {
      method: 'POST',
    })
  }

  async pullFromDropbox(resumeId: string): Promise<DropboxPullResponse> {
    return this.request<DropboxPullResponse>(`/dropbox/resumes/${encodeURIComponent(resumeId)}/pull`, {
      method: 'POST',
    })
  }

  // ---------------------------------------------------------------- //
  //  Zotero Integration (Feature 42)                                 //
  // ---------------------------------------------------------------- //

  async getZoteroStatus(): Promise<ZoteroStatusResponse> {
    return this.request<ZoteroStatusResponse>('/zotero/status')
  }

  async disconnectZotero(): Promise<{ success: boolean; message: string }> {
    return this.request('/zotero/disconnect', { method: 'DELETE' })
  }

  async getZoteroCollections(): Promise<ZoteroCollectionsResponse> {
    return this.request<ZoteroCollectionsResponse>('/zotero/collections')
  }

  async importFromZotero(resumeId: string, collectionKey?: string): Promise<ZoteroImportResponse> {
    return this.request<ZoteroImportResponse>('/zotero/import', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, collection_key: collectionKey ?? null }),
    })
  }

  // ---------------------------------------------------------------- //
  //  Mendeley Integration (Feature 42)                               //
  // ---------------------------------------------------------------- //

  async getMendeleyStatus(): Promise<MendeleyStatusResponse> {
    return this.request<MendeleyStatusResponse>('/mendeley/status')
  }

  async disconnectMendeley(): Promise<{ success: boolean; message: string }> {
    return this.request('/mendeley/disconnect', { method: 'DELETE' })
  }

  async importFromMendeley(resumeId: string, groupId?: string): Promise<MendeleyImportResponse> {
    return this.request<MendeleyImportResponse>('/mendeley/import', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, group_id: groupId ?? null }),
    })
  }

  async clearResumeBibTeX(resumeId: string): Promise<{ success: boolean }> {
    return this.request(`/zotero/bibtex/${encodeURIComponent(resumeId)}`, { method: 'DELETE' })
  }

  // ---------------------------------------------------------------- //
  //  Translation (Feature 44)                                        //
  // ---------------------------------------------------------------- //

  async translateResume(body: TranslateResumeRequest): Promise<TranslateResumeResponse> {
    return this.request<TranslateResumeResponse>('/ai/translate', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // ---------------------------------------------------------------- //
  //  Collaboration (Feature 40)                                      //
  // ---------------------------------------------------------------- //

  async inviteCollaborator(resumeId: string, email: string, role = 'editor'): Promise<CollaboratorInfo> {
    return this.request<CollaboratorInfo>(`/resumes/${encodeURIComponent(resumeId)}/collaborators`, {
      method: 'POST',
      body: JSON.stringify({ email, role }),
    })
  }

  async listCollaborators(resumeId: string): Promise<CollaboratorInfo[]> {
    return this.request<CollaboratorInfo[]>(`/resumes/${encodeURIComponent(resumeId)}/collaborators`)
  }

  async updateCollaboratorRole(resumeId: string, collabUserId: string, role: string): Promise<CollaboratorInfo> {
    return this.request<CollaboratorInfo>(
      `/resumes/${encodeURIComponent(resumeId)}/collaborators/${encodeURIComponent(collabUserId)}`,
      { method: 'PATCH', body: JSON.stringify({ role }) },
    )
  }

  async removeCollaborator(resumeId: string, collabUserId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/resumes/${encodeURIComponent(resumeId)}/collaborators/${encodeURIComponent(collabUserId)}`, {
      method: 'DELETE',
      headers: this.headers(),
    })
    if (!res.ok) {
      const body = await res.text()
      throw new Error(`Failed to remove collaborator (${res.status}): ${body}`)
    }
  }

  // ---------------------------------------------------------------- //
  //  Age Analysis (Feature 55)                                        //
  // ---------------------------------------------------------------- //

  async ageAnalysis(latex_content: string): Promise<AgeAnalysisResponse> {
    return this.request<AgeAnalysisResponse>('/ai/age-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latex_content }),
    })
  }

  // ---------------------------------------------------------------- //
  //  Contact Info Formatter (Feature 64)                              //
  // ---------------------------------------------------------------- //

  async formatContacts(latex_content: string): Promise<ContactFormatResponse> {
    return this.request<ContactFormatResponse>('/ai/format-contacts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latex_content }),
    })
  }

  // ---------------------------------------------------------------- //
  //  Reference Page Generator (Feature 70)                            //
  // ---------------------------------------------------------------- //

  async generateReferences(
    resumeId: string,
    references: ReferenceContact[]
  ): Promise<GenerateReferencesResponse> {
    return this.request<GenerateReferencesResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/generate-references`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ references }),
      }
    )
  }

  // ---------------------------------------------------------------- //
  //  Watermark compile (Feature 71)                                   //
  // ---------------------------------------------------------------- //

  async compileWatermarked(body: {
    latex_content: string
    watermark: string
    user_plan?: string
    device_fingerprint?: string
    compiler?: LatexCompiler
  }): Promise<JobSubmitResponse> {
    return this.request<JobSubmitResponse>('/jobs/compile-watermarked', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async pollJobUntilComplete(
    jobId: string,
    maxWaitMs = 120_000,
    intervalMs = 2_000,
  ): Promise<{ success: boolean }> {
    const deadline = Date.now() + maxWaitMs
    while (Date.now() < deadline) {
      const state = await this.request<{
        status: string
        stage: string
        percent: number
        last_updated: number
      }>(`/jobs/${encodeURIComponent(jobId)}/state`)
      if (state.status === 'completed') return { success: true }
      if (state.status === 'failed' || state.status === 'cancelled') return { success: false }
      await new Promise((r) => setTimeout(r, intervalMs))
    }
    throw new Error('Watermarked compile timed out')
  }

  async getResumeAnalytics(resumeId: string): Promise<ResumeAnalytics> {
    return this.request<ResumeAnalytics>(`/resumes/${encodeURIComponent(resumeId)}/analytics`)
  }

  // ---------------------------------------------------------------- //
  //  Salary Estimator (Feature 45)                                    //
  // ---------------------------------------------------------------- //

  async estimateSalary(params: SalaryEstimateRequest): Promise<SalaryEstimateResponse> {
    return this.request<SalaryEstimateResponse>('/ai/salary-estimate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
  }

  // ---------------------------------------------------------------- //
  //  Batch Tailor (Feature 75)                                        //
  // ---------------------------------------------------------------- //

  async createBatchTailor(body: BatchTailorRequest): Promise<BatchTailorResponse> {
    return this.request<BatchTailorResponse>('/jobs/batch', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async getBatchStatus(batchId: string): Promise<BatchStatusResponse> {
    return this.request<BatchStatusResponse>(`/jobs/batch/${encodeURIComponent(batchId)}`)
  }

  // ---------------------------------------------------------------- //
  //  Section Reorder (Feature 53)                                     //
  // ---------------------------------------------------------------- //

  async reorderSections(body: ReorderSectionsRequest): Promise<ReorderSectionsResponse> {
    return this.request<ReorderSectionsResponse>('/ai/reorder-sections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  }

  // ── Team Workspaces (Feature 66) ──────────────────────────────────────────

  async createWorkspace(name: string): Promise<WorkspaceResponse> {
    return this.request<WorkspaceResponse>('/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
  }

  async listWorkspaces(): Promise<WorkspaceResponse[]> {
    return this.request<WorkspaceResponse[]>('/workspaces')
  }

  async getWorkspace(workspaceId: string): Promise<WorkspaceDetailResponse> {
    return this.request<WorkspaceDetailResponse>(`/workspaces/${workspaceId}`)
  }

  async updateWorkspace(workspaceId: string, name: string): Promise<WorkspaceResponse> {
    return this.request<WorkspaceResponse>(`/workspaces/${workspaceId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
  }

  async deleteWorkspace(workspaceId: string): Promise<void> {
    await this.request<void>(`/workspaces/${workspaceId}`, { method: 'DELETE' })
  }

  async inviteWorkspaceMember(
    workspaceId: string,
    email: string,
    role: 'editor' | 'viewer' = 'editor'
  ): Promise<WorkspaceMemberResponse> {
    return this.request<WorkspaceMemberResponse>(`/workspaces/${workspaceId}/members/invite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, role }),
    })
  }

  async removeWorkspaceMember(workspaceId: string, targetUserId: string): Promise<void> {
    await this.request<void>(`/workspaces/${workspaceId}/members/${targetUserId}`, {
      method: 'DELETE',
    })
  }

  async updateWorkspaceMemberRole(
    workspaceId: string,
    targetUserId: string,
    role: 'editor' | 'viewer'
  ): Promise<WorkspaceMemberResponse> {
    return this.request<WorkspaceMemberResponse>(
      `/workspaces/${workspaceId}/members/${targetUserId}/role`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      }
    )
  }

  async addResumeToWorkspace(workspaceId: string, resumeId: string): Promise<WorkspaceResumeItem> {
    return this.request<WorkspaceResumeItem>(`/workspaces/${workspaceId}/resumes/${resumeId}`, {
      method: 'POST',
    })
  }

  async removeResumeFromWorkspace(workspaceId: string, resumeId: string): Promise<void> {
    await this.request<void>(`/workspaces/${workspaceId}/resumes/${resumeId}`, {
      method: 'DELETE',
    })
  }

  async listWorkspaceResumes(workspaceId: string): Promise<WorkspaceResumeItem[]> {
    return this.request<WorkspaceResumeItem[]>(`/workspaces/${workspaceId}/resumes`)
  }

  // ── Recruiter Notes (Feature 73) ────────────────────────────────────────────

  async createRecruiterNote(
    workspaceId: string,
    resumeId: string,
    content: string
  ): Promise<RecruiterNoteResponse> {
    return this.request<RecruiterNoteResponse>(
      `/workspaces/${workspaceId}/resumes/${resumeId}/notes`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) }
    )
  }

  async listRecruiterNotes(
    workspaceId: string,
    resumeId: string
  ): Promise<RecruiterNoteResponse[]> {
    return this.request<RecruiterNoteResponse[]>(
      `/workspaces/${workspaceId}/resumes/${resumeId}/notes`
    )
  }

  async updateRecruiterNote(
    workspaceId: string,
    resumeId: string,
    noteId: string,
    content: string
  ): Promise<RecruiterNoteResponse> {
    return this.request<RecruiterNoteResponse>(
      `/workspaces/${workspaceId}/resumes/${resumeId}/notes/${noteId}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) }
    )
  }

  async deleteRecruiterNote(
    workspaceId: string,
    resumeId: string,
    noteId: string
  ): Promise<void> {
    await this.request<void>(
      `/workspaces/${workspaceId}/resumes/${resumeId}/notes/${noteId}`,
      { method: 'DELETE' }
    )
  }

  // ── Resume Comments (Feature 74) ────────────────────────────────────────────

  async addComment(
    resumeId: string,
    content: string,
    opts?: { workspaceId?: string; lineNumber?: number; sectionTag?: string }
  ): Promise<CommentResponse> {
    return this.request<CommentResponse>(`/resumes/${resumeId}/comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content,
        workspace_id: opts?.workspaceId ?? null,
        line_number: opts?.lineNumber ?? null,
        section_tag: opts?.sectionTag ?? null,
      }),
    })
  }

  async listComments(
    resumeId: string,
    workspaceId?: string
  ): Promise<CommentResponse[]> {
    const qs = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ''
    return this.request<CommentResponse[]>(`/resumes/${resumeId}/comments${qs}`)
  }

  async updateComment(
    resumeId: string,
    commentId: string,
    content: string
  ): Promise<CommentResponse> {
    return this.request<CommentResponse>(`/resumes/${resumeId}/comments/${commentId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
  }

  async deleteComment(resumeId: string, commentId: string): Promise<void> {
    await this.request<void>(`/resumes/${resumeId}/comments/${commentId}`, { method: 'DELETE' })
  }

  async resolveComment(resumeId: string, commentId: string): Promise<CommentResponse> {
    return this.request<CommentResponse>(
      `/resumes/${resumeId}/comments/${commentId}/resolve`,
      { method: 'PATCH' }
    )
  }

  // ── Portfolio (Features 67 & 68) ─────────────────────────────────────────

  async getPortfolio(username: string): Promise<PortfolioResponse> {
    return this.request<PortfolioResponse>(`/portfolio/${encodeURIComponent(username)}`)
  }

  async setupPortfolio(body: PortfolioSetupRequest): Promise<PortfolioSetupResponse> {
    return this.request<PortfolioSetupResponse>('/portfolio/setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  }

  async checkUsernameAvailability(username: string): Promise<UsernameAvailabilityResponse> {
    return this.request<UsernameAvailabilityResponse>(
      `/portfolio/check-username?username=${encodeURIComponent(username)}`
    )
  }

  async generatePortfolioSite(resumeId: string): Promise<GeneratePortfolioResponse> {
    return this.request<GeneratePortfolioResponse>(
      `/resumes/${resumeId}/generate-portfolio`,
      { method: 'POST' }
    )
  }

  // ── Career Path (Feature 80) ───────────────────────────────────────────── //

  async analyzeCareerPath(resumeId: string, targetRoleTitle: string): Promise<CareerAnalysisResponse> {
    return this.request<CareerAnalysisResponse>('/career/analyze', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, target_role_title: targetRoleTitle }),
    })
  }

  async listCareerAnalyses(resumeId: string): Promise<CareerAnalysisResponse[]> {
    return this.request<CareerAnalysisResponse[]>(`/career/analyses/${resumeId}`)
  }

  async getCareerAnalysis(analysisId: string): Promise<CareerAnalysisResponse> {
    return this.request<CareerAnalysisResponse>(`/career/analysis/${analysisId}`)
  }

  async searchCareerRoles(q: string): Promise<CareerRoleResponse[]> {
    const params = new URLSearchParams({ q })
    return this.request<CareerRoleResponse[]>(`/career/roles?${params}`)
  }

  // ── Benchmarking (Feature 81) ──────────────────────────────────────────── //

  async getBenchmark(atsScore: number, industry?: string): Promise<BenchmarkResult> {
    const params = new URLSearchParams({ ats_score: String(atsScore) })
    if (industry) params.set('industry', industry)
    return this.request<BenchmarkResult>(`/ats/benchmark?${params}`)
  }

  // ── Snippet Marketplace (Feature 82) ────────────────────────────────────────

  async listSnippets(opts?: {
    category?: string
    q?: string
    sort?: 'popular' | 'newest' | 'official'
    offset?: number
    limit?: number
  }): Promise<SnippetResponse[]> {
    const params = new URLSearchParams()
    if (opts?.category) params.set('category', opts.category)
    if (opts?.q) params.set('q', opts.q)
    if (opts?.sort) params.set('sort', opts.sort)
    if (opts?.offset != null) params.set('offset', String(opts.offset))
    if (opts?.limit != null) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return this.request<SnippetResponse[]>(`/snippets${qs ? `?${qs}` : ''}`)
  }

  async getSnippet(snippetId: string): Promise<SnippetResponse> {
    return this.request<SnippetResponse>(`/snippets/${snippetId}`)
  }

  async createSnippet(body: SnippetCreate): Promise<SnippetResponse> {
    return this.request<SnippetResponse>('/snippets', { method: 'POST', body: JSON.stringify(body) })
  }

  async installSnippet(snippetId: string): Promise<void> {
    await this.request<void>(`/snippets/${snippetId}/install`, { method: 'POST' })
  }

  async uninstallSnippet(snippetId: string): Promise<void> {
    await this.request<void>(`/snippets/${snippetId}/install`, { method: 'DELETE' })
  }

  async upvoteSnippet(snippetId: string): Promise<void> {
    await this.request<void>(`/snippets/${snippetId}/upvote`, { method: 'POST' })
  }

  // ── Keyboard Macros (Feature 83) ─────────────────────────────────────────────

  async getMacros(): Promise<MacroResponse[]> {
    return this.request<MacroResponse[]>('/macros')
  }

  async createMacro(body: MacroCreateRequest): Promise<MacroResponse> {
    return this.request<MacroResponse>('/macros', { method: 'POST', body: JSON.stringify(body) })
  }

  async updateMacro(macroId: string, body: MacroUpdateRequest): Promise<MacroResponse> {
    return this.request<MacroResponse>(`/macros/${macroId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  }

  async deleteMacro(macroId: string): Promise<void> {
    await this.request<void>(`/macros/${macroId}`, { method: 'DELETE' })
  }

  // ── Tenant / White-Label (Feature 85) ──────────────────────────────────────

  async getCurrentTenantContext(): Promise<CurrentContextResponse> {
    return this.request<CurrentContextResponse>('/tenants/current-context')
  }

  async createTenant(body: {
    name: string
    slug: string
    plan_id?: string
    logo_url?: string | null
    primary_color?: string | null
  }): Promise<TenantResponse> {
    return this.request<TenantResponse>('/tenants', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async listMyTenants(): Promise<TenantResponse[]> {
    return this.request<TenantResponse[]>('/tenants/my')
  }

  async updateTenant(
    tenantId: string,
    body: {
      name?: string
      logo_url?: string | null
      primary_color?: string | null
      custom_domain?: string | null
      active?: boolean
    }
  ): Promise<TenantResponse> {
    return this.request<TenantResponse>(`/tenants/${tenantId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  }

  async listTenantMembers(tenantId: string): Promise<MemberResponse[]> {
    return this.request<MemberResponse[]>(`/tenants/${tenantId}/members`)
  }

  async inviteTenantMember(
    tenantId: string,
    email: string,
    role: 'admin' | 'member' = 'member'
  ): Promise<MemberResponse> {
    return this.request<MemberResponse>(`/tenants/${tenantId}/members/invite`, {
      method: 'POST',
      body: JSON.stringify({ email, role }),
    })
  }

  async removeTenantMember(tenantId: string, userId: string): Promise<void> {
    await this.request<void>(`/tenants/${tenantId}/members/${userId}`, {
      method: 'DELETE',
    })
  }

  async getTenantStats(tenantId: string): Promise<TenantStats> {
    return this.request<TenantStats>(`/tenants/${tenantId}/stats`)
  }

  async verifyTenantDomain(tenantId: string): Promise<DomainVerifyResponse> {
    return this.request<DomainVerifyResponse>(`/tenants/${tenantId}/domain/verify`, {
      method: 'POST',
    })
  }

  // ── Feature 87 — One-Click Job Applications ──────────────────────────────

  async detectJobPlatform(jobUrl: string): Promise<DetectPlatformResponse> {
    return this.request<DetectPlatformResponse>('/apply/detect', {
      method: 'POST',
      body: JSON.stringify({ job_url: jobUrl }),
    })
  }

  async previewGreenhouseJob(jobUrl: string): Promise<JobPreviewResponse> {
    return this.request<JobPreviewResponse>('/apply/greenhouse/preview', {
      method: 'POST',
      body: JSON.stringify({ job_url: jobUrl }),
    })
  }

  async previewLeverJob(jobUrl: string): Promise<JobPreviewResponse> {
    return this.request<JobPreviewResponse>('/apply/lever/preview', {
      method: 'POST',
      body: JSON.stringify({ job_url: jobUrl }),
    })
  }

  async applyGreenhouse(body: GreenhouseApplyRequest): Promise<ApplicationSubmission> {
    return this.request<ApplicationSubmission>('/apply/greenhouse', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async applyLever(body: LeverApplyRequest): Promise<ApplicationSubmission> {
    return this.request<ApplicationSubmission>('/apply/lever', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async getSubmissions(params?: { platform?: string; status?: string; limit?: number }): Promise<ApplicationSubmission[]> {
    const qs = new URLSearchParams()
    if (params?.platform) qs.set('platform', params.platform)
    if (params?.status) qs.set('status', params.status)
    if (params?.limit) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<ApplicationSubmission[]>(`/apply/submissions${suffix}`)
  }

  async getSubmission(id: string): Promise<ApplicationSubmission> {
    return this.request<ApplicationSubmission>(`/apply/submissions/${encodeURIComponent(id)}`)
  }

  // ── Feature 88 — Compile Error History ───────────────────────────────────

  async getErrorHistory(limit = 50): Promise<ErrorHistorySummary[]> {
    return this.request<ErrorHistorySummary[]>(
      `/resumes/error-history?limit=${limit}`
    )
  }

  // ── Feature 90 — Canva / Figma Export ────────────────────────────────────

  async exportCanva(resumeId: string): Promise<CanvaResumeExport> {
    return this.request<CanvaResumeExport>(`/export/${encodeURIComponent(resumeId)}/canva`)
  }

  async exportFigma(resumeId: string): Promise<FigmaResumeExport> {
    return this.request<FigmaResumeExport>(`/export/${encodeURIComponent(resumeId)}/figma`)
  }
}

// Singleton
export const apiClient = new ApiClient()

// ── Snippet Marketplace types (Feature 82) ────────────────────────────────────

export interface SnippetResponse {
  id: string
  title: string
  description: string
  content: string
  category: string
  tags: string[]
  is_official: boolean
  installs_count: number
  upvotes_count: number
  author_name: string | null
  created_at: string
  installed_by_me: boolean
  upvoted_by_me: boolean
}

export interface SnippetCreate {
  title: string
  description: string
  content: string
  category: 'header' | 'experience' | 'skills' | 'education' | 'misc'
  tags?: string[]
}

// ── Keyboard Macro types (Feature 83) ────────────────────────────────────────

export interface MacroResponse {
  id: string
  name: string
  description?: string | null
  shortcut?: string | null
  actions: Record<string, unknown>[]
  created_at: string
  updated_at: string
}

export interface MacroCreateRequest {
  name: string
  description?: string
  shortcut?: string
  actions: Record<string, unknown>[]
}

export interface MacroUpdateRequest {
  name?: string
  description?: string
  shortcut?: string
  actions?: Record<string, unknown>[]
}

// ------------------------------------------------------------------ //
//  Device fingerprint utility                                         //
// ------------------------------------------------------------------ //

export function getDeviceFingerprint(): string {
  if (typeof window === 'undefined') return 'server'
  const key = 'latexy_device_fp'
  let fp = localStorage.getItem(key)
  if (!fp) {
    fp = `fp_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
    localStorage.setItem(key, fp)
  }
  return fp
}

// ------------------------------------------------------------------ //
//  WebSocket URL builder (used by ws-client.ts)                      //
// ------------------------------------------------------------------ //

export function getWebSocketUrl(): string {
  const base =
    process.env.NEXT_PUBLIC_WS_URL ??
    (API_BASE.replace(/^http/, 'ws'))
  return `${base}/ws/jobs`
}

// ------------------------------------------------------------------ //
//  Template types                                                     //
// ------------------------------------------------------------------ //

export interface TemplateResponse {
  id: string
  name: string
  description: string | null
  category: string
  category_label: string
  tags: string[]
  thumbnail_url: string | null
  pdf_url: string | null
  sort_order: number
  document_type?: string
}

export interface TemplateDetailResponse extends TemplateResponse {
  latex_content: string
}

export interface TemplateCategoryCount {
  category: string
  label: string
  count: number
}

// ------------------------------------------------------------------ //
//  Checkpoint / version history types                                 //
// ------------------------------------------------------------------ //

export interface CheckpointEntry {
  id: string
  created_at: string
  checkpoint_label: string | null
  is_checkpoint: boolean
  is_auto_save: boolean
  optimization_level: string | null
  ats_score: number | null
  changes_count: number
  has_content: boolean
}

export interface CheckpointContentResponse {
  original_latex: string
  optimized_latex: string
  checkpoint_label: string | null
}

// ------------------------------------------------------------------ //
//  Cover letter types                                                //
// ------------------------------------------------------------------ //

export type CoverLetterTone = 'formal' | 'conversational' | 'enthusiastic'
export type CoverLetterLength = '3_paragraphs' | '4_paragraphs' | 'detailed'

export interface GenerateCoverLetterRequest {
  resume_id: string
  job_description: string
  company_name?: string
  role_title?: string
  tone: CoverLetterTone
  length_preference: CoverLetterLength
}

export interface GenerateCoverLetterResponse {
  success: boolean
  job_id: string
  cover_letter_id: string
  message: string
}

export interface CoverLetterResponse {
  id: string
  user_id: string | null
  resume_id: string
  job_description: string | null
  company_name: string | null
  role_title: string | null
  tone: string
  length_preference: string
  latex_content: string | null
  pdf_path: string | null
  generation_job_id: string | null
  created_at: string
  updated_at: string
}

export interface CoverLetterListItem extends CoverLetterResponse {
  resume_title: string
}

export interface PaginatedCoverLettersResponse {
  cover_letters: CoverLetterListItem[]
  total: number
  page: number
  limit: number
  pages: number
}

export interface CoverLetterStatsResponse {
  total: number
}

export interface QuickScoreResponse {
  score: number
  grade: string
  sections_found: string[]
  missing_sections: string[]
  keyword_match_percent: number | null
}

export interface NotificationPrefs {
  job_completed: boolean
  weekly_digest: boolean
}

// ------------------------------------------------------------------ //
//  Job Application Tracker types                                     //
// ------------------------------------------------------------------ //

export interface JobApplication {
  id: string
  user_id: string
  company_name: string
  role_title: string
  status: string
  resume_id: string | null
  ats_score_at_submission: number | null
  job_description_text: string | null
  job_url: string | null
  company_logo_url: string | null
  notes: string | null
  applied_at: string
  updated_at: string
  created_at: string
}

export interface TrackerListResponse {
  by_status: Record<string, JobApplication[]>
}

export interface TrackerStats {
  total_applications: number
  by_status: Record<string, number>
  avg_ats_score: number | null
  applications_this_week: number
  applications_this_month: number
  response_rate: number
  offer_rate: number
}

export interface CreateApplicationRequest {
  company_name: string
  role_title: string
  status?: string
  resume_id?: string
  job_description_text?: string
  job_url?: string
  notes?: string
  applied_at?: string
}

// ------------------------------------------------------------------ //
//  Interview Prep types                                              //
// ------------------------------------------------------------------ //

export interface InterviewQuestion {
  category: 'behavioral' | 'technical' | 'motivational' | 'difficult'
  question: string
  what_interviewer_assesses: string
  star_hint: string | null
}

export interface InterviewPrepResponse {
  id: string
  user_id: string | null
  resume_id: string
  job_description: string | null
  company_name: string | null
  role_title: string | null
  questions: InterviewQuestion[]
  generation_job_id: string | null
  created_at: string
  updated_at: string
}

export interface GenerateInterviewPrepRequest {
  resume_id: string
  job_description?: string
  company_name?: string
  role_title?: string
}

export interface GenerateInterviewPrepApiResponse {
  success: boolean
  job_id: string
  prep_id: string
  message: string
}

// Feature 43 — Resume View Analytics
export interface DayCount {
  date: string   // "YYYY-MM-DD"
  count: number
}
export interface CountryCount {
  country_code: string | null
  count: number
}
export interface ReferrerCount {
  referrer: string | null
  count: number
}
export interface ResumeAnalytics {
  total_views: number
  views_last_7_days: number
  views_last_30_days: number
  views_by_day: DayCount[]
  views_by_country: CountryCount[]
  views_by_referrer: ReferrerCount[]
  first_viewed_at: string | null
  last_viewed_at: string | null
}

// ------------------------------------------------------------------ //
//  Zotero / Mendeley types (Feature 42)                              //
// ------------------------------------------------------------------ //

export interface ZoteroStatusResponse {
  connected: boolean
  username: string | null
  user_id: string | null
}

export interface MendeleyStatusResponse {
  connected: boolean
  name: string | null
}

export interface ZoteroCollection {
  key: string
  name: string
}

export interface ZoteroCollectionsResponse {
  collections: ZoteroCollection[]
}

export interface ZoteroImportResponse {
  success: boolean
  entries_count: number
  bibtex: string
  message: string
}

export interface MendeleyImportResponse {
  success: boolean
  entries_count: number
  bibtex: string
  message: string
}

// ------------------------------------------------------------------ //
//  Batch Tailor (Feature 75)                                         //
// ------------------------------------------------------------------ //

export interface BatchJobItem {
  company_name: string
  role_title: string
  job_description: string
  job_url?: string
}

export interface BatchTailorRequest {
  resume_id: string
  jobs: BatchJobItem[]
}

export interface BatchTailorResponse {
  batch_id: string
  job_ids: string[]
}

export interface BatchJobStatus {
  job_id: string
  company_name: string
  role_title: string
  status: string
  variant_resume_id?: string
}

export interface BatchStatusResponse {
  batch_id: string
  status: string
  jobs: BatchJobStatus[]
}

// ------------------------------------------------------------------ //
//  Translation (Feature 44)                                          //
// ------------------------------------------------------------------ //

export interface TranslateResumeRequest {
  resume_id: string
  target_language: string   // e.g. "French"
  language_code: string     // e.g. "fr"
}

export interface TranslateResumeResponse {
  success: boolean
  variant_resume_id: string
  cached: boolean
}

// ------------------------------------------------------------------ //
//  Section Reorder (Feature 53)                                       //
// ------------------------------------------------------------------ //

export interface ReorderSectionsRequest {
  resume_latex: string
  job_description?: string
  career_stage?: string        // "entry_level" | "mid" | "senior" | "executive"
  forced_order?: string[]      // When set, backend skips LLM and applies this order directly
}

export interface ReorderSectionsResponse {
  current_order: string[]
  suggested_order: string[]
  rationale: string
  reordered_latex: string
  cached: boolean
}

// ------------------------------------------------------------------ //
//  Publications (Feature 58)                                          //
// ------------------------------------------------------------------ //

export interface GeneratePublicationsRequest {
  source?: string          // "orcid" only for MVP
  identifier: string       // ORCID ID: 0000-0000-0000-0000
  year_from?: number | null
  year_to?: number | null
  pub_types?: string[]     // ["journal", "conference", "preprint", "book_chapter"]
}

export interface PublicationOut {
  title: string
  authors: string[]
  venue: string
  year: number | null
  doi: string | null
  url: string | null
  pub_type: string
}

export interface GeneratePublicationsResponse {
  publications: PublicationOut[]
  latex_section: string
  cached: boolean
}

// ------------------------------------------------------------------ //
//  Team Workspaces (Feature 66)                                       //
// ------------------------------------------------------------------ //

export interface WorkspaceResponse {
  id: string
  name: string
  owner_id: string
  plan_id: string
  max_members: number
  member_count: number
  resume_count: number
  created_at: string
}

export interface WorkspaceMemberResponse {
  user_id: string
  email?: string
  name?: string
  role: string
  invited_at?: string
  joined_at?: string
}

export interface WorkspaceDetailResponse extends WorkspaceResponse {
  members: WorkspaceMemberResponse[]
}

export interface WorkspaceResumeItem {
  id: string
  title: string
  shared_by?: string
  shared_at: string
}

// ------------------------------------------------------------------ //
//  Recruiter Notes (Feature 73)                                       //
// ------------------------------------------------------------------ //

export interface RecruiterNoteResponse {
  id: string
  workspace_id: string
  resume_id: string
  author_id: string
  author_name?: string
  author_email?: string
  content: string
  created_at: string
  updated_at: string
}

// ------------------------------------------------------------------ //
//  Resume Comments (Feature 74)                                       //
// ------------------------------------------------------------------ //

export interface CommentResponse {
  id: string
  resume_id: string
  workspace_id?: string
  author_id: string
  author_name?: string
  author_email?: string
  content: string
  line_number?: number
  section_tag?: string
  resolved: boolean
  created_at: string
  updated_at: string
}

// ------------------------------------------------------------------ //
//  Portfolio (Features 67 & 68)                                       //
// ------------------------------------------------------------------ //

export interface PublicResumeOut {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface PortfolioResponse {
  username: string
  name?: string
  tagline?: string
  theme: string
  resumes: PublicResumeOut[]
}

export interface PortfolioSetupRequest {
  public_username: string
  portfolio_enabled?: boolean
  theme?: string
  tagline?: string
}

export interface PortfolioSetupResponse {
  public_username: string
  portfolio_enabled: boolean
  theme: string
  tagline?: string
  portfolio_url: string
}

export interface UsernameAvailabilityResponse {
  username: string
  available: boolean
}

export interface GeneratePortfolioResponse {
  portfolio_url: string
}

// ── Career Path (Feature 80) ───────────────────────────────────────────────

export interface CareerRoleResponse {
  id: string
  title: string
  level: string
  industry: string
  required_skills: string[]
  typical_yoe_min?: number | null
  typical_yoe_max?: number | null
}

export interface CareerAnalysisResponse {
  id: string
  resume_id: string
  target_role_id?: string | null
  target_role_freetext?: string | null
  current_skills: string[]
  gap_skills: string[]
  path_role_ids?: string[] | null
  timeline_months?: number | null
  llm_analysis?: string | null
  created_at: string
  path_roles?: CareerRoleResponse[] | null
  target_role?: CareerRoleResponse | null
}

// ── Tenant / White-Label (Feature 85) ─────────────────────────────────────────

export interface TenantResponse {
  id: string
  slug: string
  name: string
  logo_url?: string | null
  primary_color?: string | null
  custom_domain?: string | null
  plan_id: string
  max_members: number
  active: boolean
  owner_id: string
  created_at: string
}

export interface MemberResponse {
  user_id: string
  email: string
  name?: string | null
  role: string
  joined_at: string
}

export interface TenantStats {
  member_count: number
  total_resumes: number
  total_compilations: number
}

export interface DomainVerifyResponse {
  domain: string
  txt_record_name: string
  txt_record_value: string
  instructions: string
}

export interface CurrentContextResponse {
  tenant: {
    id: string
    slug: string
    name: string
    logo_url?: string | null
    primary_color?: string | null
    custom_domain?: string | null
    plan_id: string
    max_members: number
  } | null
}


// ── Feature 87 — One-Click Application types ─────────────────────────────────

export interface DetectPlatformResponse {
  platform: 'greenhouse' | 'lever' | 'unknown'
  company: string | null
  job_id: string | null
}

export interface JobPreviewResponse {
  platform: string
  company: string
  job_id?: string
  posting_id?: string
  title: string
  location: string
  team?: string
  apply_url: string
}

export interface GreenhouseApplyRequest {
  job_url: string
  resume_id: string
  first_name: string
  last_name: string
  email: string
  phone: string
  cover_letter?: string
}

export interface LeverApplyRequest {
  job_url: string
  resume_id: string
  name: string
  email: string
  phone: string
  org?: string
  cover_letter?: string
}

export interface ApplicationSubmission {
  id: string
  user_id: string
  resume_id: string | null
  job_tracker_id: string | null
  platform: string
  platform_job_id: string | null
  application_url: string
  job_title: string | null
  company_name: string | null
  status: 'pending' | 'submitted' | 'failed'
  submitted_at: string | null
  error_message: string | null
  created_at: string
}

// ── Feature 88 — Compile Error History ───────────────────────────────────────

export interface ErrorHistorySummary {
  error_type: string
  count: number
  last_seen: string
  last_resume_id: string | null
  last_resume_title: string | null
  example_line: string
  resolved: boolean
}

// ── Feature 90 — Canva / Figma Export ────────────────────────────────────────

export interface CanvaElement {
  type: 'HEADING' | 'TEXT' | 'DIVIDER'
  text: string
  style: Record<string, unknown>
}

export interface CanvaResumeExport {
  type: 'DESIGN'
  elements: CanvaElement[]
}

export interface FigmaEntry {
  heading: string
  subheading: string
  date: string
  bullets: string[]
}

export interface FigmaSection {
  title: string
  entries: FigmaEntry[]
}

export interface FigmaResumeExport {
  sections: FigmaSection[]
}
