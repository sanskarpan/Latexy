/**
 * Typed REST API client for Latexy.
 * Handles job submission, state polling, result fetching, and PDF download.
 * All real-time updates come through the WebSocket (ws-client.ts).
 */

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
}

export interface OptimizationHistoryEntry {
  id: string
  created_at: string
  ats_score: number | null
  changes_count: number
  tokens_used: number | null
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
  metadata?: { compiler?: string; custom_flags?: string; [key: string]: unknown } | null
  share_token?: string | null
  share_url?: string | null
  // GitHub sync (Feature 37)
  github_sync_enabled?: boolean
  github_repo_name?: string | null
  github_last_sync_at?: string | null
  created_at: string
  updated_at: string
}

export interface DiffWithParentResponse {
  parent_latex: string
  parent_title: string
  variant_latex: string
  variant_title: string
}

export interface ResumeCreate extends ResumeBase {}

export interface ResumeUpdate {
  title?: string
  latex_content?: string
  is_template?: boolean
  tags?: string[]
}

export interface ResumeStats {
  total_resumes: number
  total_templates: number
  last_updated: string | null
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
}

export interface SharedResumeResponse {
  resume_title: string
  share_token: string
  pdf_url: string
  compiled_at: string | null
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

export interface BibTeXEntry {
  identifier: string
  bibtex: string | null
  cite_key: string
  title: string | null
  authors: string | null
  year: number | null
  source_type: 'doi' | 'arxiv' | 'unknown' | null
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
    return res.json() as Promise<T>
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
    return this.request<JobSubmitResponse>('/jobs/submit', {
      method: 'POST',
      body: JSON.stringify(req),
    })
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

  async listResumes(page: number = 1, limit: number = 20): Promise<ResumeResponse[]> {
    const data = await this.request<PaginatedResumesResponse>(
      `/resumes/?page=${page}&limit=${limit}`
    )
    return data.resumes ?? []
  }

  async listResumesPaginated(page: number = 1, limit: number = 20): Promise<PaginatedResumesResponse> {
    return this.request<PaginatedResumesResponse>(
      `/resumes/?page=${page}&limit=${limit}`
    )
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
    settings: { compiler?: LatexCompiler; custom_flags?: string }
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
    })
  }

  // ---------------------------------------------------------------- //
  //  Optimization history                                             //
  // ---------------------------------------------------------------- //

  async getOptimizationHistory(resumeId: string): Promise<OptimizationHistoryEntry[]> {
    return this.request<OptimizationHistoryEntry[]>(
      `/resumes/${encodeURIComponent(resumeId)}/optimization-history`
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

  async getSubscriptionPlans(): Promise<{
    success: boolean
    data?: { plans: Record<string, unknown> }
    error?: string
  }> {
    try {
      const data = await this.request<{ plans: Record<string, unknown> }>('/subscription/plans')
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async createSubscription(
    planId: string,
    email: string,
    name: string
  ): Promise<{
    success: boolean
    data?: { shortUrl?: string; subscriptionId?: string }
    error?: string
  }> {
    try {
      const data = await this.request<{ shortUrl?: string; subscriptionId?: string }>(
        '/subscription/create',
        {
          method: 'POST',
          body: JSON.stringify({ planId, customerEmail: email, customerName: name }),
        }
      )
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

  async deepAnalyzeResume(body: {
    latex_content: string
    job_description?: string
    device_fingerprint?: string
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
  async uploadForConversion(file: File, sourceHint?: string): Promise<UploadForConversionResponse> {
    const formData = new FormData()
    formData.append('file', file)
    if (sourceHint) formData.append('source_hint', sourceHint)
    const response = await fetch(`${this.baseUrl}/formats/upload`, {
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

  async searchResumes(query: string, limit = 20): Promise<SearchResponse> {
    const params = new URLSearchParams({ q: query, limit: String(limit) })
    return this.request<SearchResponse>(`/resumes/search?${params.toString()}`)
  }

  // ---------------------------------------------------------------- //
  //  Share links                                                       //
  // ---------------------------------------------------------------- //

  async createShareLink(resumeId: string): Promise<ShareLinkResponse> {
    return this.request<ShareLinkResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/share`,
      { method: 'POST' }
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
}

// Singleton
export const apiClient = new ApiClient()

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


