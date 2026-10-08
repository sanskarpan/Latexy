/**
 * Typed REST API client for Latexy.
 * Handles job submission, state polling, result fetching, and PDF download.
 * All real-time updates come through the WebSocket (ws-client.ts).
 */

import { createTraceHeaders, trackBusinessEvent } from './telemetry'
import type { ATSDeepAnalysis } from './event-types'

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

// ------------------------------------------------------------------ //
//  Request / Response types                                           //
// ------------------------------------------------------------------ //

export type JobType =
  | 'latex_compilation'
  | 'auto_fit'
  | 'llm_optimization'
  | 'combined'
  | 'ats_scoring'
  | 'cover_letter_generation'

export type OptimizationLevel = 'conservative' | 'balanced' | 'aggressive'

export type LatexCompiler = 'pdflatex' | 'xelatex' | 'lualatex'

export const ALLOWED_LATEXMK_FLAGS = [
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
  halt_on_error?: boolean
  draft_mode?: boolean
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
  // Guided-intake direction (input-driven optimization)
  seniority?: string
  tone?: string
  emphasize?: string[]
  downplay?: string[]
  auto_fit_intensity?: number
}

/** One discrete, independently-applicable change from /optimize/segment-changes. */
export interface ChangeHunk {
  id: string
  kind: 'modified' | 'added' | 'removed'
  original_text: string
  new_text: string
  before_context: string
  after_context: string
  section: string | null
  rationale: string | null
  original_start: number
  original_end: number
}

export interface SegmentChangesResponse {
  hunks: ChangeHunk[]
  summary: { total: number; added: number; modified: number; removed: number }
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
  cohort_label?: string
  methodology?: string
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

export interface WebSocketTicketResponse {
  ticket: string
  expires_in: number
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
  /** Durable completion is retained even when its generated output is unavailable. */
  recovery_complete?: boolean
  omitted_output_fields?: string[]
  error_code?: string
  /** Null is meaningful for jobs that complete without a PDF artifact. */
  pdf_job_id?: string | null
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
  analysis_time?: number
  tokens_used?: number
  page_count?: number | null
  /** Plain text recovered from the compiled PDF by the backend extractor. */
  extracted_text?: string | null
  /** Durable deep-ATS payload used when the event stream was missed. */
  deep_analysis?: ATSDeepAnalysis
  /** Durable generated cover-letter output used when the event stream was missed. */
  cover_letter_latex?: string
  auto_fit?: boolean
  fit_succeeded?: boolean
  fit_intensity?: number
  fit_attempts?: number
  fitted_latex?: string
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
  /** "healthy" or "degraded" — degraded when any backing service below is down. */
  status: string
  version: string
  latex_available: boolean
  database?: string
  redis?: string
  /** Object storage. Its absence from this type is how a 502-ing template
   *  gallery went unnoticed while /health still reported healthy. */
  storage?: string
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

export interface SubscriptionReconciliationResponse {
  success: boolean
  status: 'reconciled' | 'pending' | 'closed' | 'unavailable'
  subscriptionId?: string
  planId?: string
  currentPeriodEnd?: string
  message?: string
}

export interface CouponValidationResponse {
  valid: boolean
  message: string
  discountPercent?: number | null
  code?: string | null
}

export interface SubscriptionCreateResponse {
  shortUrl?: string
  checkoutSessionId?: string
  subscriptionId?: string
  checkoutType?: 'hosted'
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

function httpErrorStatus(error: unknown): number | undefined {
  const message = error instanceof Error ? error.message : String(error)
  const match = message.match(/^HTTP (\d{3}):/)
  return match ? Number(match[1]) : undefined
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
  access_role?: import('@/lib/resume-access').ResumeAccessRole
  parent_resume_id?: string | null
  variant_visibility?: VariantVisibility | null
  variant_count?: number
  selected_template_id?: string | null
  content_source?: string
  builder_status?: 'active' | 'detached'
  structured_content?: StructuredResume | null
  structured_version?: number
  metadata?: { compiler?: string; custom_flags?: string; pinned?: boolean; [key: string]: unknown } | null
  share_token?: string | null
  share_url?: string | null
  share_anonymous?: boolean
  share_review_comments?: boolean
  // GitHub sync (Feature 37)
  github_sync_enabled?: boolean
  github_repo_name?: string | null
  github_last_sync_at?: string | null
  // Dropbox sync (Feature 77)
  dropbox_sync_enabled?: boolean
  dropbox_folder_path?: string | null
  dropbox_last_sync_at?: string | null
  portfolio_visible?: boolean
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

interface ResumeUpdateFields {
  title?: string
  is_template?: boolean
  tags?: string[]
  document_type?: string
  portfolio_visible?: boolean
}

interface ResumeUpdateMetadata extends ResumeUpdateFields {
  latex_content?: never
  expected_latex_content?: never
}

/**
 * Full-document writes require the source snapshot they were based on. This
 * keeps stale collaboration/autosave clients from silently clobbering newer
 * content while preserving metadata-only PATCH-like PUT compatibility.
 */
export type ResumeUpdate = ResumeUpdateMetadata | (ResumeUpdateFields & {
  latex_content: string
  expected_latex_content: string
})

export interface SuggestionDecisionRequest {
  suggestion_id: string
  status: 'accepted' | 'rejected' | 'conflicted'
  expected_content: string
  original_text: string
  replacement_text: string
  prefix?: string
  suffix?: string
}

export interface SuggestionDecisionResponse {
  suggestion_id: string
  status: 'accepted' | 'rejected' | 'conflicted'
  decided_by_role: 'owner' | 'editor'
  decided_at: string
  latex_content: string
  replayed: boolean
  replay_available: boolean
}

export interface ResumeStats {
  total_resumes: number
  total_templates: number
  last_updated: string | null
  avg_ats_score: number | null
  best_ats_score: number | null
  optimized_count: number
}

export interface UserPreferences {
  has_onboarded?: boolean
  theme?: 'light' | 'dark'
  spell_dictionary?: string[]
}

export interface MeResponse {
  id: string
  email: string
  plan: string
  role: 'user' | 'support' | 'admin'
  preferences: UserPreferences
}

export type UserPreferencesUpdate = Partial<UserPreferences>

export interface AccountPreferenceRequestContext {
  authToken: string
  isCurrent: () => boolean
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

export interface StructuredResume {
  basics: {
    name: string
    label: string
    email: string
    phone: string
    location: string
    website: string
    linkedin: string
    github: string
    summary: string
  }
  experience: Array<{
    id: string
    title: string
    company: string
    location: string
    start_date: string
    end_date: string
    current: boolean
    summary: string
    bullets: string[]
    bullet_ids: string[]
    technologies: string[]
  }>
  education: Array<{
    id: string
    institution: string
    degree: string
    field: string
    location: string
    start_date: string
    end_date: string
    gpa: string
    highlights: string[]
  }>
  projects: Array<{
    id: string
    name: string
    role: string
    url: string
    start_date: string
    end_date: string
    description: string
    bullets: string[]
    bullet_ids: string[]
    technologies: string[]
  }>
  skills: Array<{
    id: string
    name: string
    keywords: string[]
  }>
  certifications: Array<{
    id: string
    name: string
    issuer: string
    date: string
    url: string
  }>
  awards: Array<{ id: string; name: string; detail: string }>
  languages: Array<{ id: string; name: string; detail: string }>
  interests: Array<{ id: string; name: string; detail: string }>
  section_order: string[]
  hidden_sections: string[]
}

export interface VariantVisibility {
  hidden_sections: string[]
  hidden_entries: Record<string, string[]>
  hidden_list_items: Record<string, Record<string, VariantListItemSelector[]>>
}

export interface VariantListItemSelector {
  index: number
  value: string
}

export interface VariantVisibilityResponse {
  resume: ResumeResponse
  source_resume_id: string
  source_title: string
  source_content: StructuredResume
  effective_content: StructuredResume
  visibility: VariantVisibility
  metrics: BuilderMetricsResponse
  preview: BuilderPreviewResponse
  template_family: string
}

export interface BuilderTemplateResponse {
  id: string
  name: string
  description: string | null
  category: string
  category_label: string
  sort_order: number
  thumbnail_url: string | null
  pdf_url: string | null
  template_family: string
}

export interface BuilderMetricsResponse {
  completeness_score: number
  page_estimate: number
  warnings: string[]
  missing_sections: string[]
}

export interface BuilderPreviewResponse {
  template_family: string
  sections: Array<{
    key: string
    title: string
    items: unknown[]
  }>
}

export interface BuilderResumeResponse {
  resume: ResumeResponse
  metrics: BuilderMetricsResponse
  preview: BuilderPreviewResponse
  template_family: string
  ats_profile: CanonicalATSResume
}

export interface ATSPartialDate {
  value: string | null
  is_current: boolean
  found_year: boolean
  found_month: boolean
  found_day: boolean
}

export interface CanonicalATSResume {
  identity: { given_name: string; family_name: string }
  contact: { email: string; phone: string; city: string; region: string; country: string }
  links: { linkedin: string; personal_site: string }
  work: Array<{
    employer: string
    job_title: string
    start_date: ATSPartialDate
    end_date: ATSPartialDate
    is_current: boolean
    description: string
  }>
  education: Array<{
    institution: string
    degree: string
    field: string
    start_date: ATSPartialDate
    end_date: ATSPartialDate
  }>
  skills: string[]
}

export interface BuilderSeedUploadResponse {
  success: boolean
  filename: string
  format: string
  structured_content: StructuredResume
  metrics: BuilderMetricsResponse
  interchange_warnings?: string[]
}

export interface ResumeValidationIssue {
  path: string
  message: string
  line: number | null
  column: number | null
}

export class BuilderSeedValidationError extends Error {
  constructor(message: string, public readonly issues: ResumeValidationIssue[]) {
    super(message)
    this.name = 'BuilderSeedValidationError'
  }
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
//  Entitlements / Admin Control Plane                                 //
// ------------------------------------------------------------------ //

/** Per-user effective feature map from GET /config/entitlements. */
export interface EntitlementsResponse {
  features: Record<string, boolean>
}

/** A single toggleable product feature from the code-defined registry. */
export interface EntitlementFeatureDef {
  key: string
  label: string
  category: string
  gateable: boolean
  description?: string | null
}

/** Full admin entitlements state from GET /admin/entitlements. */
export interface AdminEntitlementsState {
  registry: EntitlementFeatureDef[]
  kill_switches: Record<string, boolean>
  matrix: Record<string, Record<string, boolean>>
  plan_families: string[]
}

export type UserRole = 'user' | 'support' | 'admin'

export interface AdminUser {
  id: string
  email: string
  name: string | null
  role: UserRole
  subscription_plan: string | null
  email_verified: boolean
  created_at: string
}

export interface AdminUsersResponse {
  users: AdminUser[]
  total: number
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
  public_import: boolean
  private_sync: boolean
}

export interface OAuthStartResponse {
  authorization_url: string
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

/** A single imported GitHub project (public data only). */
export interface ProjectEvidence {
  source: string
  title: string
  description: string
  tech: string[]
  metrics: { stars: number; forks: number }
  dates: { last_active: string | null }
  url: string | null
  suggested_bullets: string[]
  raw_excerpt: string
}

export interface GitHubImportResult {
  status: 'pending' | 'completed' | 'failed'
  projects: ProjectEvidence[]
  error: string | null
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

// Google Drive export (B50a). The server stores OAuth credentials; the client
// only ever receives connection state and a short-lived completion ticket.
export interface GoogleDriveStatusResponse {
  connected: boolean
  scope: 'drive.file' | null
}

export interface GoogleDriveExportResponse {
  success: true
  provider: 'google_drive'
  action: 'created' | 'updated'
  retry_behavior: 'same_file_for_resume'
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
  review_comments: boolean
}

export interface SharedResumeResponse {
  resume_title: string
  share_token: string
  pdf_url: string | null
  compiled_at: string | null
  accessible_text: string
  is_anonymous: boolean
  anonymous_processing: boolean
  review_comments: boolean
}

export interface ReviewCommentResponse {
  id: string
  reviewer_label: string
  content: string
  line_number: number | null
  section_tag: string | null
  page_number: number | null
  x: number | null
  y: number | null
  resolved: boolean
  created_at: string
  updated_at: string
}

export interface ReviewCommentCreateRequest {
  content: string
  line_number?: number | null
  section_tag?: string | null
  page_number?: number | null
  x?: number | null
  y?: number | null
}

export interface ReviewCommentListResponse {
  comments: ReviewCommentResponse[]
  /** True when older history exists outside the bounded response window. */
  truncated: boolean
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

export type PhraseSeniority = 'entry' | 'mid' | 'senior' | 'lead' | 'executive'
export type PhraseSignal = 'high_impact' | 'ats_friendly' | 'leadership' | 'technical_depth'

export interface PhraseLibraryRequest {
  job_title: string
  seniority: PhraseSeniority
  industry: string
  skill_category: string
  count?: number
}

export interface PhraseLibraryResponse extends Omit<PhraseLibraryRequest, 'count'> {
  phrases: Array<{ text: string; signals: PhraseSignal[] }>
  cached: boolean
}

export type RewriteAction =
  | 'improve'
  | 'shorten'
  | 'quantify'
  | 'power_verbs'
  | 'change_tone'
  | 'expand'
  | 'steer'
  | 'paraphrase'
  | 'concise'
  | 'scientific'
  | 'split'
  | 'join'

export interface RewriteRequest {
  selected_text: string
  action: RewriteAction
  context?: string
  tone?: string
  /** Free-text steer for the 'steer' action (regenerate-with-a-note). */
  instruction?: string
}

export interface RewriteResponse {
  rewritten: string
  action: string
  cached: boolean
}

export interface DocumentAssistantTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface DocumentAssistantRequest {
  resume_id: string
  latex_content: string
  message: string
  history?: DocumentAssistantTurn[]
  selected_text?: string
}

export interface DocumentAssistantResponse {
  message: string
  proposed_edit: {
    target_text: string
    replacement_text: string
  } | null
}

export interface SynonymsResponse {
  synonyms: string[]
  cached: boolean
}

export interface GenerateLatexRequest {
  intent: string
  document_context?: string
}

export interface GenerateLatexResponse {
  latex: string
  cached: boolean
}

export interface GenerateLatexTableRequest {
  table_text: string
  first_row_header?: boolean
}

export interface GenerateLatexTableResponse {
  latex: string
  rows: number
  columns: number
  source: 'text' | 'image'
}

export type MathDisplayMode = 'inline' | 'display' | 'equation'

export interface GenerateLatexMathRequest {
  math_text: string
  display_mode?: MathDisplayMode
}

export interface GenerateLatexMathResponse {
  latex: string
  display_mode: MathDisplayMode
  source: 'text' | 'image'
  cached: boolean
}

export interface BulletVariantSet {
  id: string
  resume_id: string
  source_text: string
  target_label: string
  options: string[]
  created_at: string
  updated_at: string
}

export interface GenerateBulletVariantsRequest {
  resume_id: string
  source_text: string
  job_description?: string
  target_label?: string
}

export type ResumeElementType = 'bullet' | 'paragraph' | 'equation' | 'figure' | 'other'
export type ElementVersionSource = 'manual' | 'ai' | 'import' | 'restore' | 'fork'
export type ElementVersionOperation = 'create' | 'edit' | 'restore' | 'fork'

export interface ResumeElementVersion {
  id: string
  resume_id: string
  element_key: string
  element_type: ResumeElementType
  content: string
  content_hash: string
  parent_version_id: string | null
  root_version_id: string
  operation: ElementVersionOperation
  source: ElementVersionSource
  provenance: Record<string, string | number | boolean | null>
  application_id: string | null
  created_at: string
  tracker_evidence?: {
    application_id: string
    company_name: string
    role_title: string
    status: string
    applied_at: string
    source: 'user_tracker'
    interpretation: string
  } | null
}

export interface ResumeElementVersionPage {
  items: ResumeElementVersion[]
  next_cursor: string | null
}

export interface CreateResumeElementVersionRequest {
  element_key: string
  element_type?: ResumeElementType
  content: string
  source?: ElementVersionSource
  operation?: ElementVersionOperation
  provenance?: Record<string, string | number | boolean | null>
  parent_version_id?: string
  expected_head_version_id?: string
  application_id?: string
  idempotency_key?: string
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

export interface CitationVerification {
  cite_key: string
  status: 'verified' | 'mismatch' | 'not_found' | 'error'
  source: 'crossref' | 'arxiv'
  identifier: string | null
  matched_title: string | null
  matched_authors: string | null
  matched_year: number | null
  title_similarity: number | null
  issues: string[]
}

export interface VerifyCitationsResponse {
  results: CitationVerification[]
  total: number
  verified: number
  mismatched: number
  processing_time: number
}

/**
 * Extracts a clean, human-readable message from a failed response body.
 *
 * FastAPI's `HTTPException` responses look like `{"detail": "..."}`; Pydantic
 * validation errors look like `{"detail": [{"msg": "...", ...}, ...]}`. Both
 * shapes are unwrapped into plain text here so that no downstream catch-site
 * (toast, banner) ever has to guess how to render an error — it just reads
 * `.message`. Without this, callers were dumping the raw JSON body (or a full
 * exception string) straight into the UI.
 *
 * Falls back to a short raw body / statusText / fallbackLabel when the body
 * isn't a recognizable JSON error shape, so failures are never swallowed —
 * only genuinely un-parseable bodies (long HTML error pages, etc.) are capped.
 */
function parseApiErrorMessage(bodyText: string, statusText: string, fallbackLabel?: string): string {
  const trimmed = bodyText.trim()
  if (trimmed) {
    try {
      const parsed: unknown = JSON.parse(trimmed)
      const detail = (parsed as { detail?: unknown } | null)?.detail
      if (typeof detail === 'string' && detail.trim()) return detail
      if (Array.isArray(detail) && detail.length > 0) {
        const messages = detail
          .map((d) =>
            d && typeof d === 'object' && 'msg' in d
              ? String((d as { msg?: unknown }).msg)
              : typeof d === 'string'
                ? d
                : null
          )
          .filter((m): m is string => Boolean(m))
        if (messages.length > 0) return messages.join('; ')
      }
      const message = (parsed as { message?: unknown } | null)?.message
      if (typeof message === 'string' && message.trim()) return message
      // Recognizable JSON, but no known error field — don't dump the raw object.
    } catch {
      // Not JSON. A short plain-text body (e.g. from a proxy/load balancer) is
      // still readable; a long one (HTML error pages) is not, so cap it.
      if (trimmed.length <= 200 && !trimmed.startsWith('<')) return trimmed
    }
  }
  return statusText || fallbackLabel || 'Request failed'
}

class ApiClient {
  private authToken: string | null = null
  private tenantSlug: string | null = null
  readonly baseUrl: string = API_BASE

  // The Better Auth session is resolved asynchronously on the client, so AuthSync
  // can only hand us the Bearer token a tick or two after the first paint. Any
  // component fetching on mount would otherwise race it and get an un-retried 401.
  // `authReady` makes outbound requests wait until AuthSync has reported the
  // session state (a real token, or an explicit null for anonymous visitors).
  //
  // The wait is *bounded*: if the Better Auth session endpoint is slow or hangs,
  // we fall through after AUTH_READY_TIMEOUT_MS and send the request without a
  // token instead of deadlocking the app — including anonymous flows such as /try
  // and share pages, which need no token at all.
  // On the server there is no AuthSync, so the gate starts open.
  private static readonly AUTH_READY_TIMEOUT_MS = 8000
  private authReady: Promise<void> = Promise.resolve()
  private resolveAuthReady: (() => void) | null = null
  private authDeadlineStarted = false
  private jobListContextVersion = 0
  private listJobsInFlight: Promise<{ jobs: JobStateResponse[] }> | null = null

  constructor() {
    if (typeof window !== 'undefined') {
      const match = document.cookie.match(/(?:^|;\s*)latexy_tenant_slug=([^;]+)/)
      const cookieSlug = match ? decodeURIComponent(match[1]) : ''
      if (/^[a-z0-9-]{3,40}$/.test(cookieSlug)) this.tenantSlug = cookieSlug
      const reported = new Promise<void>((resolve) => {
        this.resolveAuthReady = resolve
      })
      this.authReady = reported
    }
  }

  // Fallback leg of the auth gate — opens it if AuthSync never reports in.
  private authReadyDeadline(): Promise<void> {
    return new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        if (this.resolveAuthReady) {
          const release = this.resolveAuthReady
          this.resolveAuthReady = null
          release()
          console.warn(
            '[apiClient] auth session did not resolve within ' +
              `${ApiClient.AUTH_READY_TIMEOUT_MS}ms — proceeding unauthenticated`
          )
        }
        resolve()
      }, ApiClient.AUTH_READY_TIMEOUT_MS)
      // Never keep a test runner / SSR process alive just for this timer.
      ;(timer as unknown as { unref?: () => void }).unref?.()
    })
  }

  private async waitForAuthReady(): Promise<void> {
    if (!this.resolveAuthReady) return
    if (!this.authDeadlineStarted) {
      this.authDeadlineStarted = true
      void this.authReadyDeadline()
    }
    await this.authReady
  }

  setAuthToken(token: string | null): void {
    if (this.authToken !== token) {
      this.jobListContextVersion += 1
      this.listJobsInFlight = null
    }
    this.authToken = token
    // Only a real token opens the gate here. Pages that mirror their own session
    // token into the client must not be able to open it with a null while
    // AuthSync is still hydrating — that is precisely the race the gate exists to
    // prevent. AuthSync calls markAuthResolved() for the anonymous case.
    if (token) this.markAuthResolved()
  }

  // Called by AuthSync once the Better Auth session state is known, including
  // when there is no session at all.
  markAuthResolved(): void {
    this.resolveAuthReady?.()
    this.resolveAuthReady = null
  }

  getAuthToken(): string | null {
    return this.authToken
  }

  setTenantSlug(slug: string | null): void {
    const nextSlug = slug && /^[a-z0-9-]{3,40}$/.test(slug) ? slug : null
    if (this.tenantSlug !== nextSlug) {
      this.jobListContextVersion += 1
      this.listJobsInFlight = null
    }
    this.tenantSlug = nextSlug
  }

  private headers(extra: Record<string, string> = {}, includeJsonContentType: boolean = true): HeadersInit {
    const h: Record<string, string> = {
      ...(typeof window !== 'undefined' ? createTraceHeaders() : {}),
      ...extra,
    }
    if (includeJsonContentType && !('Content-Type' in h)) {
      h['Content-Type'] = 'application/json'
    }
    if (this.authToken) h['Authorization'] = `Bearer ${this.authToken}`
    if (this.tenantSlug) h['X-Tenant-Slug'] = this.tenantSlug
    for (const [key, value] of Object.entries(h)) {
      if (value === '') delete h[key]
    }
    return h
  }

  private shouldSendJsonContentType(init: RequestInit): boolean {
    const method = (init.method ?? 'GET').toUpperCase()
    if (method === 'GET' || method === 'HEAD') return false
    if (init.body == null) return false
    return !(typeof FormData !== 'undefined' && init.body instanceof FormData)
  }

  // Single entry point for every authenticated fetch. It waits for the auth gate
  // and builds the headers *after* the wait, so the guarantee is structural: no
  // call site can accidentally send a request with a not-yet-published token.
  private async authedFetch(
    url: string,
    init: RequestInit = {},
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<Response> {
    await this.waitForAuthReady()
    if (
      accountContext
      && (this.authToken !== accountContext.authToken || !accountContext.isCurrent())
    ) {
      throw new Error('Account request context changed before dispatch')
    }
    const headers: Record<string, string> = {
      ...(this.headers({}, this.shouldSendJsonContentType(init)) as Record<string, string>),
      ...((init.headers as Record<string, string> | undefined) ?? {}),
    }
    if (headers['Content-Type'] === '') {
      delete headers['Content-Type']
    }
    return fetch(url, { ...init, headers })
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<T> {
    const res = await this.authedFetch(`${API_BASE}${path}`, init, accountContext)
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
    }
    if (res.status === 204) {
      return undefined as T
    }
    const responseHeaders = res.headers as
      | { get?: (name: string) => string | null }
      | Record<string, string>
      | undefined
    const plainResponseHeaders =
      typeof responseHeaders?.get === 'function'
        ? undefined
        : (responseHeaders as Record<string, string> | undefined)
    const contentType =
      (typeof responseHeaders?.get === 'function'
        ? responseHeaders.get('content-type')
        : plainResponseHeaders?.['content-type'] ?? plainResponseHeaders?.['Content-Type']) || ''
    if (contentType.includes('application/json') || (!contentType && typeof res.json === 'function')) {
      return res.json() as Promise<T>
    }
    if (contentType) {
      throw new Error(`Unexpected response type ${contentType} from ${path}`)
    }
    return (await res.text()) as T
  }

  // ---------------------------------------------------------------- //
  //  Health                                                           //
  // ---------------------------------------------------------------- //

  async health(): Promise<HealthResponse> {
    return this.request<HealthResponse>('/health')
  }

  async createWebSocketTicket(
    purpose: 'jobs' | 'collab',
    resumeId?: string,
  ): Promise<WebSocketTicketResponse> {
    return this.request<WebSocketTicketResponse>('/ws/ticket', {
      method: 'POST',
      body: JSON.stringify({
        purpose,
        resume_id: purpose === 'collab' ? resumeId : undefined,
      }),
    })
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
    // Backend shape is { success, job_id, result: {...}, error }. Unwrap `result`
    // into the flat JobResultResponse the rest of the app expects.
    const raw = await this.request<{
      success: boolean
      job_id: string
      result?: Record<string, unknown>
      error?: string
    }>(`/jobs/${encodeURIComponent(jobId)}/result`)
    if (raw.job_id !== jobId) {
      throw new Error('Job result identity mismatch')
    }
    const nestedJobId = raw.result?.job_id
    if (typeof nestedJobId === 'string' && nestedJobId !== raw.job_id) {
      throw new Error('Nested job result identity mismatch')
    }
    // The envelope is the owner-scoped identity boundary. A stale/corrupt
    // nested payload must not be relabeled as the requested job before
    // useJobStream validates the recovered result.
    return {
      ...(raw.result || {}),
      success: raw.success,
      job_id: raw.job_id,
      error: raw.error,
    } as JobResultResponse
  }

  async listJobs(): Promise<{ jobs: JobStateResponse[] }> {
    await this.waitForAuthReady()
    if (this.listJobsInFlight) return this.listJobsInFlight
    const contextVersion = this.jobListContextVersion
    // Match the FastAPI route's canonical trailing slash. Calling `/jobs`
    // forces a 307 + second request, doubling this fetch on every dashboard
    // refresh and spending two rate-limit units for one logical read.
    const pending = this.request<{ jobs: JobStateResponse[] }>('/jobs/').then((result) => {
      if (this.jobListContextVersion !== contextVersion) {
        throw new Error('Job-list authentication context changed. Please retry.')
      }
      return result
    })
    this.listJobsInFlight = pending
    try {
      return await pending
    } finally {
      if (this.listJobsInFlight === pending) this.listJobsInFlight = null
    }
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

  async listResumesPaginated(page: number = 1, limit: number = 20, archived = false): Promise<PaginatedResumesResponse> {
    return this.request<PaginatedResumesResponse>(
      `/resumes/?page=${page}&limit=${limit}${archived ? '&archived=true' : ''}`
    )
  }

  /** Load every resume page for library and picker surfaces. */
  async listAllResumes(archived = false): Promise<ResumeResponse[]> {
    const limit = 200
    const first = await this.listResumesPaginated(1, limit, archived)
    const resumes = [...(first.resumes ?? [])]
    const pages = Math.max(first.pages ?? 1, Math.ceil((first.total ?? resumes.length) / limit))
    for (let page = 2; page <= pages; page += 1) {
      const next = await this.listResumesPaginated(page, limit, archived)
      resumes.push(...(next.resumes ?? []))
    }
    return resumes
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

  async getBuilderTemplates(): Promise<BuilderTemplateResponse[]> {
    return this.request<BuilderTemplateResponse[]>('/resumes/builder/templates')
  }

  async seedBuilderFromUpload(file: File): Promise<BuilderSeedUploadResponse> {
    const form = new FormData()
    form.append('file', file)
    const res = await this.authedFetch(`${API_BASE}/resumes/builder/seed-upload`, {
      method: 'POST',
      body: form,
      credentials: 'include',
    })
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      try {
        const payload = JSON.parse(bodyText) as {
          error?: { code?: unknown; message?: unknown; details?: { issues?: unknown } }
        }
        const issues = payload.error?.details?.issues
        if (payload.error?.code === 'resume_validation_error' && Array.isArray(issues)) {
          throw new BuilderSeedValidationError(
            typeof payload.error.message === 'string' ? payload.error.message : 'Resume data failed validation.',
            issues as ResumeValidationIssue[],
          )
        }
      } catch (error) {
        if (error instanceof BuilderSeedValidationError) throw error
      }
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
    }
    return res.json()
  }

  async createBuilderResume(body: {
    title: string
    template_id: string
    structured_content?: StructuredResume
  }): Promise<BuilderResumeResponse> {
    return this.request<BuilderResumeResponse>('/resumes/builder', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async getBuilderResume(resumeId: string): Promise<BuilderResumeResponse> {
    return this.request<BuilderResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/builder`)
  }

  async updateBuilderResume(
    resumeId: string,
    body: {
      title?: string
      template_id?: string
      structured_content?: StructuredResume
      force_reattach?: boolean
    }
  ): Promise<BuilderResumeResponse> {
    return this.request<BuilderResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/builder`, {
      method: 'PATCH',
      body: JSON.stringify(body),
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

  /**
   * Atomically decide a collaboration suggestion on the server. The backend
   * compares expected_content while locking the resume row and returns the
   * exact committed source so a client can recover after a pre-Yjs crash.
   */
  async decideSuggestion(
    resumeId: string,
    decision: SuggestionDecisionRequest,
  ): Promise<SuggestionDecisionResponse> {
    return this.request<SuggestionDecisionResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/suggestion-decisions`,
      {
        method: 'POST',
        body: JSON.stringify(decision),
      },
    )
  }

  /** Confirm a peer's Y.Map decision against the server before changing UI state. */
  async getSuggestionDecision(
    resumeId: string,
    suggestionId: string,
  ): Promise<SuggestionDecisionResponse> {
    return this.request<SuggestionDecisionResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/suggestion-decisions/${encodeURIComponent(suggestionId)}`,
    )
  }

  async deleteResume(resumeId: string): Promise<void> {
    const res = await this.authedFetch(`${API_BASE}/resumes/${encodeURIComponent(resumeId)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, res.statusText, `Delete failed (${res.status})`))
    }
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
    const res = await this.authedFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, res.statusText, `Cancel failed (${res.status})`))
    }
  }

  // ---------------------------------------------------------------- //
  //  PDF download                                                     //
  // ---------------------------------------------------------------- //

  getPdfUrl(jobId: string): string {
    return `${API_BASE}/download/${encodeURIComponent(jobId)}`
  }

  async downloadPdf(jobId: string, signal?: AbortSignal): Promise<Blob> {
    const res = await this.authedFetch(this.getPdfUrl(jobId), { signal })
    if (!res.ok) throw new Error(`PDF download failed: HTTP ${res.status}`)
    return res.blob()
  }

  async downloadSynctex(jobId: string, signal?: AbortSignal): Promise<string | null> {
    const res = await this.authedFetch(
      `${API_BASE}/download/${encodeURIComponent(jobId)}/synctex`,
      { signal },
    )
    // SyncTeX is an optional enhancement. A compile may legitimately omit it,
    // so callers should quietly disable source↔PDF sync rather than surface a
    // document-preview error.
    if (!res.ok) return null
    return res.text()
  }

  async getPdfBlobUrl(jobId: string): Promise<{ url: string; revoke: () => void }> {
    const blob = await this.downloadPdf(jobId)
    const url = URL.createObjectURL(blob)
    return { url, revoke: () => URL.revokeObjectURL(url) }
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

  async autoFitResume(body: {
    latex_content: string
    resume_id: string
    compiler?: LatexCompiler
    intensity?: number
  }): Promise<JobSubmitResponse> {
    return this.submitJob({
      job_type: 'auto_fit',
      latex_content: body.latex_content,
      metadata: { resume_id: body.resume_id },
      compiler: body.compiler,
      auto_fit_intensity: body.intensity,
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
    // Guided-intake direction (input-driven optimization)
    industry?: string
    seniority?: string
    tone?: string
    emphasize?: string[]
    downplay?: string[]
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
      industry: body.industry,
      seniority: body.seniority,
      tone: body.tone,
      emphasize: body.emphasize,
      downplay: body.downplay,
    })
  }

  async getPersonas(): Promise<Array<{ key: string; label: string; description: string }>> {
    return this.request('/ai/personas')
  }

  // ---------------------------------------------------------------- //
  //  Per-change review (input-driven optimization, F2-P0)             //
  // ---------------------------------------------------------------- //

  /**
   * Segment the original→optimized diff into discrete, individually-applicable
   * change hunks (server-side, deterministic). The frontend renders these for
   * accept/reject/edit, then calls {@link applyChanges} with the accepted ids.
   */
  async segmentChanges(body: {
    original_latex: string
    optimized_latex: string
    change_reasons?: Array<{ section?: string; change_type?: string; reason?: string }>
  }): Promise<SegmentChangesResponse> {
    return this.request<SegmentChangesResponse>('/optimize/segment-changes', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  /** Reconstruct the final LaTeX from the original + the accepted hunk ids. */
  async applyChanges(body: {
    original_latex: string
    hunks: ChangeHunk[]
    accepted_ids: string[]
  }): Promise<{ latex: string }> {
    return this.request<{ latex: string }>('/optimize/apply-changes', {
      method: 'POST',
      body: JSON.stringify(body),
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
    status: string
    redis?: Record<string, boolean>
    timestamp?: number
    error?: string
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

  async reconcileSubscription(): Promise<{
    success: boolean
    data?: SubscriptionReconciliationResponse
    error?: string
  }> {
    try {
      const data = await this.request<SubscriptionReconciliationResponse>(
        '/subscription/reconcile',
        { method: 'POST' },
      )
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
      billingPeriod?: 'monthly' | 'annual' | 'weekly' | 'lifetime'
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
    data?: { success: boolean; message: string; shortUrl?: string }
    error?: string
  }> {
    try {
      const data = await this.request<{
        success: boolean
        message: string
        short_url?: string
      }>(`/subscription/student/verify/${encodeURIComponent(token)}`)
      return { success: true, data: { ...data, shortUrl: data.short_url } }
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

  async previewTeamSeat(token: string): Promise<{
    success: boolean
    data?: { success: boolean; message: string }
    error?: string
    status?: number
  }> {
    try {
      const data = await this.request<{ success: boolean; message: string }>(
        `/team/join/${encodeURIComponent(token)}`,
      )
      return { success: true, data }
    } catch (e) {
      return {
        success: false,
        error: e instanceof Error ? e.message : String(e),
        status: httpErrorStatus(e),
      }
    }
  }

  async joinTeamSeat(token: string): Promise<{
    success: boolean
    data?: { success: boolean; message: string }
    error?: string
    status?: number
  }> {
    try {
      const data = await this.request<{ success: boolean; message: string }>(
        `/team/join/${encodeURIComponent(token)}`,
        { method: 'POST' },
      )
      return { success: true, data }
    } catch (e) {
      return {
        success: false,
        error: e instanceof Error ? e.message : String(e),
        status: httpErrorStatus(e),
      }
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

  async getATSLocaleProfiles(): Promise<{
    success: boolean
    threshold: number
    profiles: Array<{ key: string; label: string; calibration: string }>
  }> {
    return this.request('/ats/locale-profiles')
  }

  /**
   * Synchronous ATS score — used for an immediate re-score when the user
   * overrides the industry calibration (see ATSScoreCard). Hits the same
   * `ats_scoring_service` computation as the async job path, just without
   * the Celery round-trip, so the score/recommendations shown stay in sync
   * with the chosen industry profile.
   */
  async scoreATS(body: {
    latex_content: string
    job_description?: string
    industry_override?: string
    locale?: 'global' | 'india' | 'united_states' | 'united_kingdom'
  }): Promise<{
    success: boolean
    ats_score?: number
    category_scores?: Record<string, number>
    recommendations?: string[]
    warnings?: string[]
    strengths?: string[]
    industry_key?: string
    industry_label?: string
    locale_key?: string
    locale_label?: string
    score_threshold?: number
    calibration_statement?: string
    message: string
  }> {
    return this.request('/ats/score', {
      method: 'POST',
      body: JSON.stringify({ ...body, async_processing: false }),
    })
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
    const response = await this.authedFetch(url.toString(), {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      const bodyText = await response.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, response.statusText, `Upload failed (${response.status})`))
    }
    return response.json()
  }

  // Parse a file and return basic preview data (no LLM conversion)
  async parseForPreview(file: File): Promise<ParsePreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await this.authedFetch(`${this.baseUrl}/formats/parse`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      const bodyText = await response.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, response.statusText, `Parse failed (${response.status})`))
    }
    return response.json()
  }

  // Export a saved resume in a specific format (returns Blob for download)
  async exportResume(resumeId: string, format: string): Promise<Blob> {
    const response = await this.authedFetch(`${this.baseUrl}/export/${resumeId}/${format}`)
    if (!response.ok) {
      const bodyText = await response.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, response.statusText, `Export failed (${response.status})`))
    }
    return response.blob()
  }

  async emailResumePdf(resumeId: string): Promise<EmailDocumentResponse> {
    return this.request<EmailDocumentResponse>(
      `/export/${encodeURIComponent(resumeId)}/email`,
      { method: 'POST', body: JSON.stringify({}) },
    )
  }

  async getEmailResumePdfStatus(resumeId: string): Promise<DocumentEmailDeliveryStatus> {
    return this.request<DocumentEmailDeliveryStatus>(
      `/export/${encodeURIComponent(resumeId)}/email/status`,
    )
  }

  async retryEmailResumePdf(resumeId: string): Promise<EmailDocumentResponse> {
    return this.request<EmailDocumentResponse>(
      `/export/${encodeURIComponent(resumeId)}/email/retry`,
      { method: 'POST', body: JSON.stringify({}) },
    )
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
    const res = await this.authedFetch(
      `${API_BASE}/resumes/${encodeURIComponent(resumeId)}/checkpoints/${encodeURIComponent(checkpointId)}`,
      { method: 'DELETE' }
    )
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, res.statusText, `Delete failed (${res.status})`))
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

  async getVariantVisibility(resumeId: string): Promise<VariantVisibilityResponse> {
    return this.request<VariantVisibilityResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/variant-visibility`,
    )
  }

  async updateVariantVisibility(
    resumeId: string,
    body: { title?: string; visibility: VariantVisibility },
  ): Promise<VariantVisibilityResponse> {
    return this.request<VariantVisibilityResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/variant-visibility`,
      { method: 'PATCH', body: JSON.stringify(body) },
    )
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
    const response = await this.authedFetch(`${this.baseUrl}/export/content/${format}`, {
      method: 'POST',
      body: JSON.stringify({ latex_content: latexContent }),
    })
    if (!response.ok) {
      const bodyText = await response.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, response.statusText, `Export failed (${response.status})`))
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

  async useTemplate(id: string, title?: string, locale?: string): Promise<{ resume_id: string; title: string }> {
    return this.request<{ resume_id: string; title: string }>(
      `/templates/${encodeURIComponent(id)}/use`,
      { method: 'POST', body: JSON.stringify({ title: title || null, locale: locale || null }) }
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
    await this.authedFetch(`${API_BASE}/cover-letters/${encodeURIComponent(id)}`, {
      method: 'DELETE',
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

  async generatePhraseLibrary(body: PhraseLibraryRequest): Promise<PhraseLibraryResponse> {
    return this.request<PhraseLibraryResponse>('/ai/phrase-library', {
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

  async askDocumentAssistant(
    body: DocumentAssistantRequest,
  ): Promise<DocumentAssistantResponse> {
    return this.request<DocumentAssistantResponse>('/ai/document-assistant', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async suggestSynonyms(text: string, context?: string, count = 5): Promise<SynonymsResponse> {
    return this.request<SynonymsResponse>('/ai/synonyms', {
      method: 'POST',
      body: JSON.stringify({ text, context, count }),
    })
  }

  async generateLatex(body: GenerateLatexRequest): Promise<GenerateLatexResponse> {
    return this.request<GenerateLatexResponse>('/ai/generate-latex', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async generateLatexTable(body: GenerateLatexTableRequest): Promise<GenerateLatexTableResponse> {
    return this.request<GenerateLatexTableResponse>('/ai/generate-table', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async generateLatexTableFromImage(file: File, firstRowHeader = true): Promise<GenerateLatexTableResponse> {
    const form = new FormData()
    form.append('file', file)
    form.append('first_row_header', String(firstRowHeader))
    return this.request<GenerateLatexTableResponse>('/ai/generate-table-image', {
      method: 'POST',
      body: form,
    })
  }

  async generateLatexMath(body: GenerateLatexMathRequest): Promise<GenerateLatexMathResponse> {
    return this.request<GenerateLatexMathResponse>('/ai/generate-math', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async generateLatexMathFromImage(
    file: File,
    displayMode: MathDisplayMode = 'display',
  ): Promise<GenerateLatexMathResponse> {
    const form = new FormData()
    form.append('file', file)
    form.append('display_mode', displayMode)
    return this.request<GenerateLatexMathResponse>('/ai/generate-math-image', {
      method: 'POST',
      body: form,
    })
  }

  async generateBulletVariants(body: GenerateBulletVariantsRequest): Promise<BulletVariantSet> {
    return this.request<BulletVariantSet>('/ai/bullet-variants', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async getBulletVariants(resumeId: string): Promise<BulletVariantSet[]> {
    return this.request<BulletVariantSet[]>(
      `/ai/bullet-variants?resume_id=${encodeURIComponent(resumeId)}`
    )
  }

  async deleteBulletVariantSet(variantSetId: string): Promise<void> {
    await this.request<void>(`/ai/bullet-variants/${encodeURIComponent(variantSetId)}`, {
      method: 'DELETE',
    })
  }

  async createResumeElementVersion(
    resumeId: string,
    body: CreateResumeElementVersionRequest,
  ): Promise<ResumeElementVersion> {
    return this.request<ResumeElementVersion>(`/resumes/${encodeURIComponent(resumeId)}/element-versions`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async getResumeElementVersions(
    resumeId: string,
    elementKey: string,
    options: { limit?: number; cursor?: string } = {},
  ): Promise<ResumeElementVersionPage> {
    const params = new URLSearchParams({ element_key: elementKey })
    if (options.limit !== undefined) params.set('limit', String(options.limit))
    if (options.cursor) params.set('cursor', options.cursor)
    return this.request<ResumeElementVersionPage>(
      `/resumes/${encodeURIComponent(resumeId)}/element-versions?${params.toString()}`,
    )
  }

  async restoreResumeElementVersion(
    resumeId: string,
    versionId: string,
    expectedHeadVersionId: string,
    idempotencyKey?: string,
  ): Promise<ResumeElementVersion> {
    return this.request<ResumeElementVersion>(
      `/resumes/${encodeURIComponent(resumeId)}/element-versions/${encodeURIComponent(versionId)}/restore`,
      {
        method: 'POST',
        body: JSON.stringify({ expected_head_version_id: expectedHeadVersionId, idempotency_key: idempotencyKey }),
      },
    )
  }

  async forkResumeElementVersion(
    resumeId: string,
    versionId: string,
    expectedHeadVersionId: string,
    idempotencyKey?: string,
  ): Promise<ResumeElementVersion> {
    return this.request<ResumeElementVersion>(
      `/resumes/${encodeURIComponent(resumeId)}/element-versions/${encodeURIComponent(versionId)}/fork`,
      {
        method: 'POST',
        body: JSON.stringify({ expected_head_version_id: expectedHeadVersionId, idempotency_key: idempotencyKey }),
      },
    )
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

  async verifyCitations(bibtex: string): Promise<VerifyCitationsResponse> {
    return this.request<VerifyCitationsResponse>('/references/verify', {
      method: 'POST',
      body: JSON.stringify({ bibtex }),
    })
  }

  async searchResumes(query: string, limit = 20): Promise<SearchResponse> {
    const params = new URLSearchParams({ q: query, limit: String(limit) })
    return this.request<SearchResponse>(`/resumes/search?${params.toString()}`)
  }

  // ---------------------------------------------------------------- //
  //  Share links                                                       //
  // ---------------------------------------------------------------- //

  async createShareLink(
    resumeId: string,
    anonymous = false,
    regenerateAnonymous = false,
    reviewComments?: boolean,
  ): Promise<ShareLinkResponse> {
    return this.request<ShareLinkResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/share`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          anonymous,
          ...(regenerateAnonymous ? { regenerate_anonymous: true } : {}),
          ...(reviewComments === undefined ? {} : { review_comments: reviewComments }),
        }),
      }
    )
  }

  async revokeShareLink(resumeId: string): Promise<void> {
    const res = await this.authedFetch(
      `${API_BASE}/resumes/${encodeURIComponent(resumeId)}/share`,
      { method: 'DELETE' }
    )
    if (!res.ok && res.status !== 204) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
    }
  }

  async getSharedResume(shareToken: string): Promise<SharedResumeResponse> {
    return this.request<SharedResumeResponse>(`/share/${encodeURIComponent(shareToken)}`)
  }

  async listPublicReviewComments(shareToken: string): Promise<ReviewCommentResponse[]> {
    return this.request<ReviewCommentResponse[]>(
      `/share/${encodeURIComponent(shareToken)}/review-comments`,
    )
  }

  async addPublicReviewComment(
    shareToken: string,
    body: ReviewCommentCreateRequest,
  ): Promise<ReviewCommentResponse> {
    return this.request<ReviewCommentResponse>(
      `/share/${encodeURIComponent(shareToken)}/review-comments`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
  }

  async listReviewComments(resumeId: string): Promise<ReviewCommentListResponse> {
    const res = await this.authedFetch(
      `${API_BASE}/resumes/${encodeURIComponent(resumeId)}/review-comments`,
    )
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
    }
    return {
      comments: await res.json() as ReviewCommentResponse[],
      truncated: res.headers.get('X-Review-Comments-Truncated') === 'true',
    }
  }

  async resolveReviewComment(
    resumeId: string,
    commentId: string,
    resolved: boolean,
  ): Promise<ReviewCommentResponse> {
    return this.request<ReviewCommentResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/review-comments/${encodeURIComponent(commentId)}/resolve`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolved }),
      },
    )
  }

  // ---------------------------------------------------------------- //
  //  Bulk export (Feature 49)                                         //
  // ---------------------------------------------------------------- //

  async bulkExport(format: 'tex' | 'pdf' | 'docx'): Promise<Blob> {
    const res = await this.authedFetch(
      `${API_BASE}/resumes/export/bulk?format=${format}`
    )
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
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
  //  Entitlements — Admin Control Plane                              //
  // ---------------------------------------------------------------- //

  /** Per-user effective feature map (auth optional; anonymous → free map). */
  async getEntitlements(): Promise<EntitlementsResponse> {
    return this.request<EntitlementsResponse>('/config/entitlements')
  }

  /** Full admin entitlements state: registry, kill-switches, matrix, plan families. */
  async getAdminEntitlements(): Promise<AdminEntitlementsState> {
    return this.request<AdminEntitlementsState>('/admin/entitlements')
  }

  /** Toggle a feature's global kill-switch. Returns fresh state. */
  async updateKillSwitch(key: string, enabled: boolean): Promise<AdminEntitlementsState> {
    return this.request<AdminEntitlementsState>(
      `/admin/entitlements/kill-switch/${encodeURIComponent(key)}`,
      { method: 'PATCH', body: JSON.stringify({ enabled }) },
    )
  }

  /** Toggle a single feature × plan-family matrix cell. Returns fresh state. */
  async updateMatrixCell(
    planFamily: string,
    featureKey: string,
    enabled: boolean,
  ): Promise<AdminEntitlementsState> {
    return this.request<AdminEntitlementsState>('/admin/entitlements/matrix', {
      method: 'PATCH',
      body: JSON.stringify({
        plan_family: planFamily,
        feature_key: featureKey,
        enabled,
      }),
    })
  }

  async getAdminUsers(params?: {
    q?: string
    limit?: number
    offset?: number
  }): Promise<AdminUsersResponse> {
    const qs = new URLSearchParams()
    if (params?.q) qs.set('q', params.q)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.offset != null) qs.set('offset', String(params.offset))
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminUsersResponse>(`/admin/users${suffix}`)
  }

  /**
   * Update a user's role. Throws on 409 (last_admin guard) — the thrown
   * Error message contains "409" and the "last_admin" code for callers.
   */
  async updateUserRole(id: string, role: UserRole): Promise<AdminUser> {
    return this.request<AdminUser>(`/admin/users/${encodeURIComponent(id)}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
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
    const res = await this.authedFetch(`${API_BASE}/tracker/applications/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
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

  async listStaleApplications(days = 14): Promise<StaleApplication[]> {
    return this.request<StaleApplication[]>(`/tracker/stale-applications?days=${encodeURIComponent(days)}`)
  }

  async getStaleApplications(days = 14): Promise<StaleApplication[]> {
    return this.listStaleApplications(days)
  }

  async createOutreachDraft(body: OutreachDraftRequest): Promise<OutreachDraftResponse> {
    return this.request<OutreachDraftResponse>('/outreach/drafts', { method: 'POST', body: JSON.stringify(body) })
  }

  async parseTrackerEmailStatus(body: EmailStatusParseRequest): Promise<EmailStatusParseResponse> {
    return this.request<EmailStatusParseResponse>('/tracker/email-status/parse', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async createSavedJob(body: SavedJobCreateRequest): Promise<SavedJob> {
    return this.request<SavedJob>('/tracker/saved-jobs', { method: 'POST', body: JSON.stringify(body) })
  }

  async listSavedJobs(): Promise<SavedJob[]> {
    return this.request<SavedJob[]>('/tracker/saved-jobs')
  }

  async updateSavedJob(id: string, body: SavedJobUpdateRequest): Promise<SavedJob> {
    return this.request<SavedJob>(`/tracker/saved-jobs/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) })
  }

  async deleteSavedJob(id: string): Promise<void> {
    return this.request<void>(`/tracker/saved-jobs/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  async bulkDeleteSavedJobs(ids: string[]): Promise<void> {
    const params = new URLSearchParams()
    ids.forEach((id) => params.append('ids', id))
    return this.request<void>(`/tracker/saved-jobs?${params.toString()}`, { method: 'DELETE' })
  }

  async trackSavedJob(id: string, body: TrackSavedJobRequest = {}): Promise<TrackSavedJobResponse> {
    return this.request<TrackSavedJobResponse>(`/tracker/saved-jobs/${encodeURIComponent(id)}/track`, { method: 'POST', body: JSON.stringify(body) })
  }

  async createAlert(body: JobAlertCreateRequest): Promise<JobAlert> {
    return this.request<JobAlert>('/tracker/alerts', { method: 'POST', body: JSON.stringify(body) })
  }

  async listAlerts(): Promise<JobAlert[]> {
    return this.request<JobAlert[]>('/tracker/alerts')
  }

  async updateAlert(id: string, body: JobAlertUpdateRequest): Promise<JobAlert> {
    return this.request<JobAlert>(`/tracker/alerts/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) })
  }

  async deleteAlert(id: string): Promise<void> {
    return this.request<void>(`/tracker/alerts/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  async createApplicationReminder(applicationId: string, body: ReminderCreateRequest): Promise<ApplicationReminder> {
    return this.request<ApplicationReminder>(`/tracker/applications/${encodeURIComponent(applicationId)}/reminders`, { method: 'POST', body: JSON.stringify(body) })
  }

  async listApplicationReminders(applicationId: string): Promise<ApplicationReminder[]> {
    return this.request<ApplicationReminder[]>(`/tracker/applications/${encodeURIComponent(applicationId)}/reminders`)
  }

  async createReminder(applicationId: string, body: ReminderCreateRequest): Promise<ApplicationReminder> {
    return this.createApplicationReminder(applicationId, body)
  }

  async listReminders(applicationId: string): Promise<ApplicationReminder[]> {
    return this.listApplicationReminders(applicationId)
  }

  async deleteApplicationReminder(applicationId: string, reminderId: string): Promise<void> {
    return this.request<void>(`/tracker/applications/${encodeURIComponent(applicationId)}/reminders/${encodeURIComponent(reminderId)}`, { method: 'DELETE' })
  }

  async updateApplicationReminder(applicationId: string, reminderId: string, body: ReminderCreateRequest): Promise<ApplicationReminder> {
    return this.request<ApplicationReminder>(`/tracker/applications/${encodeURIComponent(applicationId)}/reminders/${encodeURIComponent(reminderId)}`, { method: 'PUT', body: JSON.stringify(body) })
  }

  async deleteReminder(applicationId: string, reminderId: string): Promise<void> {
    return this.deleteApplicationReminder(applicationId, reminderId)
  }

  async updateReminder(applicationId: string, reminderId: string, body: ReminderCreateRequest): Promise<ApplicationReminder> {
    return this.updateApplicationReminder(applicationId, reminderId, body)
  }

  async createApplicationInterview(applicationId: string, body: InterviewCreateRequest): Promise<ApplicationInterview> {
    return this.request<ApplicationInterview>(`/tracker/applications/${encodeURIComponent(applicationId)}/interviews`, { method: 'POST', body: JSON.stringify(body) })
  }

  async listApplicationInterviews(applicationId: string): Promise<ApplicationInterview[]> {
    return this.request<ApplicationInterview[]>(`/tracker/applications/${encodeURIComponent(applicationId)}/interviews`)
  }

  async createInterview(applicationId: string, body: InterviewCreateRequest): Promise<ApplicationInterview> {
    return this.createApplicationInterview(applicationId, body)
  }

  async listInterviews(applicationId: string): Promise<ApplicationInterview[]> {
    return this.listApplicationInterviews(applicationId)
  }

  async updateApplicationInterview(applicationId: string, interviewId: string, body: InterviewUpdateRequest): Promise<ApplicationInterview> {
    return this.request<ApplicationInterview>(`/tracker/applications/${encodeURIComponent(applicationId)}/interviews/${encodeURIComponent(interviewId)}`, { method: 'PUT', body: JSON.stringify(body) })
  }

  async deleteApplicationInterview(applicationId: string, interviewId: string): Promise<void> {
    return this.request<void>(`/tracker/applications/${encodeURIComponent(applicationId)}/interviews/${encodeURIComponent(interviewId)}`, { method: 'DELETE' })
  }

  async updateInterview(applicationId: string, interviewId: string, body: InterviewUpdateRequest): Promise<ApplicationInterview> {
    return this.updateApplicationInterview(applicationId, interviewId, body)
  }

  async deleteInterview(applicationId: string, interviewId: string): Promise<void> {
    return this.deleteApplicationInterview(applicationId, interviewId)
  }

  async downloadApplicationInterviewIcs(applicationId: string, interviewId: string): Promise<Blob> {
    const res = await this.authedFetch(`${API_BASE}/tracker/applications/${encodeURIComponent(applicationId)}/interviews/${encodeURIComponent(interviewId)}.ics`)
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
    }
    return res.blob()
  }

  async downloadInterviewIcs(applicationId: string, interviewId: string): Promise<Blob> {
    return this.downloadApplicationInterviewIcs(applicationId, interviewId)
  }

  async createTrackerCompany(body: TrackerCompanyCreateRequest): Promise<TrackerCompany> {
    return this.request<TrackerCompany>('/tracker/companies', { method: 'POST', body: JSON.stringify(body) })
  }

  async listTrackerCompanies(): Promise<TrackerCompany[]> {
    return this.request<TrackerCompany[]>('/tracker/companies')
  }

  async createCompany(body: TrackerCompanyCreateRequest): Promise<TrackerCompany> {
    return this.createTrackerCompany(body)
  }

  async listCompanies(): Promise<TrackerCompany[]> {
    return this.listTrackerCompanies()
  }

  async updateTrackerCompany(id: string, body: TrackerCompanyUpdateRequest): Promise<TrackerCompany> {
    return this.request<TrackerCompany>(`/tracker/companies/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) })
  }

  async updateCompany(id: string, body: TrackerCompanyUpdateRequest): Promise<TrackerCompany> {
    return this.updateTrackerCompany(id, body)
  }

  async deleteTrackerCompany(id: string): Promise<void> {
    return this.request<void>(`/tracker/companies/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  async deleteCompany(id: string): Promise<void> {
    return this.deleteTrackerCompany(id)
  }

  async createTrackerContact(body: TrackerContactCreateRequest): Promise<TrackerContact> {
    return this.request<TrackerContact>('/tracker/contacts', { method: 'POST', body: JSON.stringify(body) })
  }

  async listTrackerContacts(): Promise<TrackerContact[]> {
    return this.request<TrackerContact[]>('/tracker/contacts')
  }

  async createContact(body: TrackerContactCreateRequest): Promise<TrackerContact> {
    return this.createTrackerContact(body)
  }

  async listContacts(): Promise<TrackerContact[]> {
    return this.listTrackerContacts()
  }

  async updateTrackerContact(id: string, body: TrackerContactUpdateRequest): Promise<TrackerContact> {
    return this.request<TrackerContact>(`/tracker/contacts/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) })
  }

  async updateContact(id: string, body: TrackerContactUpdateRequest): Promise<TrackerContact> {
    return this.updateTrackerContact(id, body)
  }

  async deleteTrackerContact(id: string): Promise<void> {
    return this.request<void>(`/tracker/contacts/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  async deleteContact(id: string): Promise<void> {
    return this.deleteTrackerContact(id)
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
    const res = await this.authedFetch(`${API_BASE}/interview-prep/${encodeURIComponent(prepId)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
    }
  }

  async evaluateInterviewSimulation(
    prepId: string,
    body: EvaluateInterviewSimulationRequest,
  ): Promise<EvaluateInterviewSimulationResponse> {
    return this.request<EvaluateInterviewSimulationResponse>(
      `/interview-prep/${encodeURIComponent(prepId)}/simulate`,
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  // ---------------------------------------------------------------- //
  //  Account (me) + synced UI preferences                            //
  // ---------------------------------------------------------------- //

  async getMe(accountContext?: AccountPreferenceRequestContext): Promise<MeResponse> {
    return this.request<MeResponse>('/me', {}, accountContext)
  }

  async updateMePreferences(
    prefs: UserPreferencesUpdate,
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<MeResponse> {
    return this.request<MeResponse>('/me/preferences', {
      method: 'PATCH',
      body: JSON.stringify(prefs),
    }, accountContext)
  }

  // ---------------------------------------------------------------- //
  //  Notification preferences (Feature 19)                           //
  // ---------------------------------------------------------------- //

  async getNotificationPrefs(accountContext?: AccountPreferenceRequestContext): Promise<NotificationPrefs> {
    return this.request<NotificationPrefs>('/settings/notifications', {}, accountContext)
  }

  async updateNotificationPrefs(
    prefs: NotificationPrefs,
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<NotificationPrefs> {
    return this.request<NotificationPrefs>('/settings/notifications', {
      method: 'PUT',
      body: JSON.stringify(prefs),
    }, accountContext)
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

  async getGitHubStatus(accountContext?: AccountPreferenceRequestContext): Promise<GitHubStatusResponse> {
    return this.request<GitHubStatusResponse>('/github/status', {}, accountContext)
  }

  async startGitHubOAuth(
    purpose: 'import' | 'sync' = 'import',
    returnTo?: string,
  ): Promise<OAuthStartResponse> {
    const params = new URLSearchParams({ purpose })
    if (returnTo) params.set('return_to', returnTo)
    return this.request<OAuthStartResponse>(`/github/connect?${params.toString()}`, {
      method: 'POST',
    })
  }

  async completeGitHubOAuth(ticket: string, accountContext?: AccountPreferenceRequestContext): Promise<{ success: boolean; message: string }> {
    return this.request('/github/complete', {
      method: 'POST',
      body: JSON.stringify({ ticket }),
    }, accountContext)
  }

  async disconnectGitHub(accountContext?: AccountPreferenceRequestContext): Promise<{ success: boolean; message: string }> {
    return this.request('/github/disconnect', { method: 'DELETE' }, accountContext)
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

  /**
   * Start an async import of the user's top PUBLIC GitHub projects (F1). Returns
   * a job id to poll via {@link getGitHubImportResult}. Requires a connected
   * GitHub account (400 otherwise).
   */
  async importGitHubProjects(): Promise<{ job_id: string }> {
    return this.request<{ job_id: string }>('/github/import-projects', { method: 'POST' })
  }

  /** Poll a GitHub-import job for its ranked, AI-summarized ProjectEvidence. */
  async getGitHubImportResult(jobId: string): Promise<GitHubImportResult> {
    return this.request<GitHubImportResult>(`/github/import-projects/${encodeURIComponent(jobId)}`)
  }

  /**
   * Import projects from a public portfolio / personal-site URL (F1 Phase 2).
   * Synchronous — one SSRF-guarded fetch + one LLM call server-side.
   */
  async importFromUrl(url: string): Promise<{ projects: ProjectEvidence[] }> {
    return this.request<{ projects: ProjectEvidence[] }>('/sources/import-url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    })
  }

  /**
   * Import projects from a user-uploaded LinkedIn data-export ZIP or resume file
   * (F1 Phase 3 — compliant, parsed locally server-side, never scrapes LinkedIn).
   */
  async importLinkedIn(file: File): Promise<{ projects: ProjectEvidence[] }> {
    const form = new FormData()
    form.append('file', file)
    const res = await this.authedFetch(`${API_BASE}/sources/import-linkedin`, {
      method: 'POST',
      body: form,
      credentials: 'include',
    })
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
    }
    return res.json()
  }

  // ---------------------------------------------------------------- //
  //  Dropbox Integration (Feature 77)                               //
  // ---------------------------------------------------------------- //

  async getDropboxStatus(): Promise<DropboxStatusResponse> {
    return this.request<DropboxStatusResponse>('/dropbox/status')
  }

  async startDropboxOAuth(): Promise<OAuthStartResponse> {
    return this.request<OAuthStartResponse>('/dropbox/connect', { method: 'POST' })
  }

  async completeDropboxOAuth(ticket: string): Promise<{ success: boolean; message: string }> {
    return this.request('/dropbox/complete', {
      method: 'POST',
      body: JSON.stringify({ ticket }),
    })
  }

  async disconnectDropbox(accountContext?: AccountPreferenceRequestContext): Promise<{ success: boolean; message: string }> {
    return this.request('/dropbox/disconnect', { method: 'DELETE' }, accountContext)
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
  //  Google Drive export (B50a)                                      //
  // ---------------------------------------------------------------- //

  async getGoogleDriveStatus(accountContext?: AccountPreferenceRequestContext): Promise<GoogleDriveStatusResponse> {
    return this.request<GoogleDriveStatusResponse>('/google-drive/status', {}, accountContext)
  }

  async startGoogleDriveOAuth(): Promise<OAuthStartResponse> {
    return this.request<OAuthStartResponse>('/google-drive/connect', { method: 'POST' })
  }

  async completeGoogleDriveOAuth(ticket: string): Promise<{ success: boolean; message: string }> {
    return this.request('/google-drive/complete', {
      method: 'POST',
      body: JSON.stringify({ ticket }),
    })
  }

  async disconnectGoogleDrive(accountContext?: AccountPreferenceRequestContext): Promise<{ success: boolean; message: string }> {
    return this.request('/google-drive/disconnect', { method: 'DELETE' }, accountContext)
  }

  async exportResumeToGoogleDrive(resumeId: string): Promise<GoogleDriveExportResponse> {
    return this.request<GoogleDriveExportResponse>(
      `/google-drive/resumes/${encodeURIComponent(resumeId)}/export`,
      { method: 'POST', body: JSON.stringify({}) },
    )
  }

  // ---------------------------------------------------------------- //
  //  Zotero Integration (Feature 42)                                 //
  // ---------------------------------------------------------------- //

  async getZoteroStatus(): Promise<ZoteroStatusResponse> {
    return this.request<ZoteroStatusResponse>('/zotero/status')
  }

  async startZoteroOAuth(): Promise<OAuthStartResponse> {
    return this.request<OAuthStartResponse>('/zotero/connect', { method: 'POST' })
  }

  async completeZoteroOAuth(ticket: string): Promise<{ success: boolean; message: string }> {
    return this.request('/zotero/complete', {
      method: 'POST',
      body: JSON.stringify({ ticket }),
    })
  }

  async disconnectZotero(accountContext?: AccountPreferenceRequestContext): Promise<{ success: boolean; message: string }> {
    return this.request('/zotero/disconnect', { method: 'DELETE' }, accountContext)
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

  async startMendeleyOAuth(): Promise<OAuthStartResponse> {
    return this.request<OAuthStartResponse>('/mendeley/connect', { method: 'POST' })
  }

  async completeMendeleyOAuth(ticket: string): Promise<{ success: boolean; message: string }> {
    return this.request('/mendeley/complete', {
      method: 'POST',
      body: JSON.stringify({ ticket }),
    })
  }

  async disconnectMendeley(accountContext?: AccountPreferenceRequestContext): Promise<{ success: boolean; message: string }> {
    return this.request('/mendeley/disconnect', { method: 'DELETE' }, accountContext)
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
    const res = await this.authedFetch(`${API_BASE}/resumes/${encodeURIComponent(resumeId)}/collaborators/${encodeURIComponent(collabUserId)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, res.statusText, `Failed to remove collaborator (${res.status})`))
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

  async downloadWorkspaceResume(workspaceId: string, resumeId: string): Promise<Blob> {
    const response = await this.authedFetch(
      `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/resumes/${encodeURIComponent(resumeId)}/download`,
    )
    if (!response.ok) {
      const body = await response.text().catch(() => '')
      throw new Error(`HTTP ${response.status}: ${parseApiErrorMessage(body, response.statusText)}`)
    }
    return response.blob()
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
    opts?: { workspaceId?: string; lineNumber?: number; sectionTag?: string; mentionedUserIds?: string[] }
  ): Promise<CommentResponse> {
    return this.request<CommentResponse>(`/resumes/${resumeId}/comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content,
        workspace_id: opts?.workspaceId ?? null,
        line_number: opts?.lineNumber ?? null,
        section_tag: opts?.sectionTag ?? null,
        mentioned_user_ids: opts?.mentionedUserIds ?? null,
      }),
    })
  }

  async listCommentParticipants(
    resumeId: string,
    workspaceId?: string,
  ): Promise<CommentMentionParticipant[]> {
    const qs = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ''
    return this.request<CommentMentionParticipant[]>(
      `/resumes/${encodeURIComponent(resumeId)}/comments/participants${qs}`,
    )
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
    content: string,
    mentionedUserIds?: string[],
  ): Promise<CommentResponse> {
    return this.request<CommentResponse>(`/resumes/${resumeId}/comments/${commentId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, mentioned_user_ids: mentionedUserIds ?? null }),
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

  async sendPortfolioContact(
    username: string,
    body: { name: string; email: string; message: string },
  ): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      `/portfolio/${encodeURIComponent(username)}/contact`,
      { method: 'POST', body: JSON.stringify(body) },
    )
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

  async searchCareerSkills(
    q: string,
    language = 'en',
    limit = 8,
  ): Promise<CareerSkillSearchResponse> {
    const params = new URLSearchParams({ q, language, limit: String(limit) })
    return this.request<CareerSkillSearchResponse>(`/career/skills?${params}`)
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

  async executeMacro(
    macroId: string,
    body: MacroExecuteRequest,
  ): Promise<MacroExecuteResponse> {
    return this.request<MacroExecuteResponse>(`/macros/${macroId}/execute`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // ── Tenant / White-Label (Feature 85) ──────────────────────────────────────

  async getCurrentTenantContext(): Promise<CurrentContextResponse> {
    return this.request<CurrentContextResponse>('/tenants/current-context')
  }

  async resolveTenantHost(host: string): Promise<CurrentContextResponse> {
    const context = await this.request<CurrentContextResponse>(
      `/tenants/resolve-host?host=${encodeURIComponent(host)}`,
    )
    this.setTenantSlug(context.tenant?.slug ?? null)
    return context
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
    role: 'admin' | 'member' = 'member',
    cohortId?: string,
  ): Promise<TenantInvitationResponse> {
    return this.request<TenantInvitationResponse>(`/tenants/${tenantId}/members/invite`, {
      method: 'POST',
      body: JSON.stringify({ email, role, cohort_id: cohortId }),
    })
  }

  async removeTenantMember(tenantId: string, userId: string): Promise<void> {
    await this.request<void>(`/tenants/${tenantId}/members/${userId}`, {
      method: 'DELETE',
    })
  }

  async acceptTenantInvitation(token: string): Promise<MemberResponse> {
    return this.request<MemberResponse>(`/tenants/invitations/${encodeURIComponent(token)}/accept`, {
      method: 'POST',
    })
  }

  async leaveTenant(tenantId: string): Promise<void> {
    await this.request<void>(`/tenants/${tenantId}/membership`, { method: 'DELETE' })
  }

  async createTenantCohort(tenantId: string, name: string): Promise<TenantCohort> {
    return this.request<TenantCohort>(`/tenants/${tenantId}/cohorts`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    })
  }

  async listTenantCohorts(tenantId: string): Promise<TenantCohort[]> {
    return this.request<TenantCohort[]>(`/tenants/${tenantId}/cohorts`)
  }

  async listCohortSubmissions(tenantId: string, cohortId: string): Promise<CohortSubmission[]> {
    return this.request<CohortSubmission[]>(
      `/tenants/${tenantId}/cohorts/${cohortId}/submissions`,
    )
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
  script?: string | null
  script_version: number
  script_hash?: string | null
  /** True when pre-cap recorded actions were quarantined and cannot execute. */
  legacy_actions_available: boolean
  created_at: string
  updated_at: string
}

export interface MacroCreateRequest {
  name: string
  description?: string
  shortcut?: string
  actions: Record<string, unknown>[]
  script?: string | null
}

export interface MacroUpdateRequest {
  name?: string
  description?: string | null
  shortcut?: string | null
  actions?: Record<string, unknown>[]
  script?: string | null
  expected_script_version?: number
}

export interface MacroExecuteRequest {
  document: string
  expected_script_version?: number
}

export interface MacroExecuteResponse {
  document: string
  script_version: number
  script_hash: string
  operation_count: number
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

/** Absolute ws(s):// origin every socket hangs off. */
export function getWebSocketBase(): string {
  return process.env.NEXT_PUBLIC_WS_URL ?? API_BASE.replace(/^http/, 'ws')
}

export function getWebSocketUrl(): string {
  return `${getWebSocketBase()}/ws/jobs`
}

/**
 * Base URL for the Y.js collaboration socket; y-websocket appends the room id.
 * Must share the /ws/ prefix with the jobs socket: in production
 * NEXT_PUBLIC_API_URL is the same-origin path "/api", and nginx's `location
 * /api/` caps concurrent connections per IP (limit_conn 10). A long-lived
 * editor socket routed there would burn one of those slots per open tab and
 * 503 all REST traffic for everyone behind the same NAT.
 */
export function getCollabWebSocketUrl(): string {
  return `${getWebSocketBase()}/ws/collab`
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
  document_type: 'resume' | 'presentation' | 'academic_cv'
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
  job_failed: boolean
  share_viewed: boolean
  weekly_digest: boolean
  tracker_updates: boolean
  comment_mentions: boolean
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

export interface StaleApplication extends JobApplication {
  days_since_update: number
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

export interface SavedJob {
  id: string
  company_name: string
  role_title: string
  job_url: string | null
  job_description_text: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface SavedJobCreateRequest {
  company_name: string
  role_title: string
  job_url?: string | null
  job_description_text?: string | null
  notes?: string | null
}

export type SavedJobUpdateRequest = { [K in keyof SavedJobCreateRequest]?: SavedJobCreateRequest[K] | null }

export interface TrackSavedJobRequest {
  status?: string
  resume_id?: string
  applied_at?: string
}

export interface TrackSavedJobResponse {
  application_id: string
  saved_job_deleted: boolean
}

export interface JobAlert {
  id: string
  query: string
  company_name: string | null
  location: string | null
  source_url: string
  frequency: 'daily' | 'weekly'
  active: boolean
  last_notified_at: string | null
  created_at: string
  updated_at: string
}

export interface JobAlertCreateRequest {
  query: string
  company_name?: string | null
  location?: string | null
  source_url: string
  frequency?: 'daily' | 'weekly'
  active?: boolean
}

export type JobAlertUpdateRequest = { [K in keyof JobAlertCreateRequest]?: JobAlertCreateRequest[K] | null }

export interface ApplicationReminder {
  id: string
  application_id: string
  remind_at: string
  note: string | null
  sent_at: string | null
  created_at: string
}

export interface ReminderCreateRequest {
  remind_at: string
  note?: string | null
}

export type InterviewFormat = 'phone' | 'video' | 'onsite' | 'take_home' | 'other'

export interface ApplicationInterview {
  id: string
  application_id: string
  round_name: string
  interview_format: InterviewFormat
  starts_at: string
  duration_minutes: number
  timezone: string
  location: string | null
  interviewers: string[]
  notes: string | null
  created_at: string
  updated_at: string
}

export interface InterviewCreateRequest {
  round_name: string
  interview_format: InterviewFormat
  starts_at: string
  duration_minutes?: number
  timezone?: string
  location?: string | null
  interviewers?: string[]
  notes?: string | null
}

export type InterviewUpdateRequest = { [K in keyof InterviewCreateRequest]?: InterviewCreateRequest[K] | null }

export interface TrackerCompany {
  id: string
  name: string
  website: string | null
  notes: string | null
  created_at: string
}

export interface TrackerCompanyCreateRequest {
  name: string
  website?: string | null
  notes?: string | null
}

export type TrackerCompanyUpdateRequest = { [K in keyof TrackerCompanyCreateRequest]?: TrackerCompanyCreateRequest[K] | null }

export interface TrackerContact {
  id: string
  company_id: string | null
  name: string
  role_title: string | null
  email: string | null
  phone: string | null
  linkedin_url: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface TrackerContactCreateRequest {
  company_id?: string | null
  name: string
  role_title?: string | null
  email?: string | null
  phone?: string | null
  linkedin_url?: string | null
  notes?: string | null
}

export type TrackerContactUpdateRequest = { [K in keyof TrackerContactCreateRequest]?: TrackerContactCreateRequest[K] | null }

export type OutreachChannel = 'email' | 'linkedin'
export type OutreachPurpose = 'referral_request' | 'follow_up' | 'thank_you' | 'networking'

export interface OutreachDraftRequest {
  application_id: string
  contact_id?: string | null
  channel?: OutreachChannel
  purpose?: OutreachPurpose
  additional_context?: string | null
}

export interface OutreachDraftResponse {
  application_id: string
  contact_id: string | null
  recipient_name: string | null
  recipient_role: string | null
  company_name: string
  role_title: string
  stage: string
  channel: OutreachChannel
  purpose: OutreachPurpose
  subject: string
  body: string
  placeholders: string[]
  editable: boolean
  sent: boolean
}

export interface EmailStatusEvidence {
  signal: string
  source: string
}

export interface EmailStatusParseRequest {
  raw_email: string
}

export interface EmailStatusParseResponse {
  status: string | null
  company: string | null
  role: string | null
  confidence: number
  company_confidence: number
  role_confidence: number
  evidence: EmailStatusEvidence[]
  requires_review: boolean
}

export interface EmailDocumentResponse {
  status: 'accepted'
  recipient: 'verified_account_email'
  retry_behavior: 'provider_idempotent' | 'smtp_best_effort'
}

export interface DocumentEmailDeliveryStatus {
  id: string
  status: 'pending' | 'processing' | 'accepted' | 'failed'
  attempts: number
  retryable: boolean
  accepted_at: string | null
}

// ------------------------------------------------------------------ //
//  Interview Prep types                                              //
// ------------------------------------------------------------------ //

export interface InterviewQuestion {
  category: 'behavioral' | 'technical' | 'motivational' | 'difficult'
  question: string
  what_interviewer_assesses: string
  star_hint: string | null
  /** Present on screening-prep sessions generated after the B11b rollout. */
  ideal_response_outline?: string[]
  spoken_answer_tip?: string
  recommended_seconds?: number
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

export type InterviewSimulationMode = 'coach' | 'mock'

export interface InterviewSimulationAnswer {
  question_index: number
  answer: string
}

export interface InterviewSimulationFeedback {
  question_index: number
  score: number
  strengths: string[]
  improvements: string[]
  suggested_outline: string[]
}

export interface EvaluateInterviewSimulationRequest {
  mode: InterviewSimulationMode
  answers: InterviewSimulationAnswer[]
}

export interface EvaluateInterviewSimulationResponse {
  mode: InterviewSimulationMode
  feedback: InterviewSimulationFeedback[]
  average_score: number
  overall_feedback: string
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
  source: ReferenceLibrarySource
}

export interface MendeleyImportResponse {
  success: boolean
  entries_count: number
  bibtex: string
  message: string
  source: ReferenceLibrarySource
}

export interface ReferenceLibrarySource {
  provider: 'zotero' | 'mendeley'
  scope: 'library' | 'collection' | 'group'
  scope_id: string | null
  filename: 'references.bib'
  read_only: true
  synced_at: string
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
  citation_style?: 'cv' | 'apa' | 'ieee'
}

export interface PublicationOut {
  title: string
  authors: string[]
  venue: string
  year: number | null
  doi: string | null
  url: string | null
  pub_type: string
  latex_entry: string
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
  owner_id: string
  shared_by?: string
  shared_at: string
  opened_at?: string | null
  opened_actor?: 'candidate' | null
  opened_source?: 'candidate_self' | null
  downloaded_at?: string | null
  downloaded_actor?: 'candidate' | null
  downloaded_source?: 'candidate_self' | null
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
  mentions: CommentMention[]
}

export interface CommentMention {
  user_id: string
  display_name: string
}

export interface CommentMentionParticipant extends CommentMention {
  email?: string | null
}

// ------------------------------------------------------------------ //
//  Portfolio (Features 67 & 68)                                       //
// ------------------------------------------------------------------ //

export interface PublicResumeOut {
  id: string
  title: string
  created_at: string
  updated_at: string
  accessible_text: string
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
  skill_taxonomy?: string | null
  skill_taxonomy_language?: string | null
  skill_taxonomy_mappings?: CareerSkillTaxonomyMapping[] | null
  path_role_ids?: string[] | null
  timeline_months?: number | null
  llm_analysis?: string | null
  created_at: string
  path_roles?: CareerRoleResponse[] | null
  target_role?: CareerRoleResponse | null
}

export interface CareerSkillTaxonomyMapping {
  input: string
  preferred_label: string
  uri?: string | null
  matched: boolean
}

export interface CareerSkillSearchResult {
  uri: string
  preferred_label: string
  alternative_labels: string[]
  language: string
}

export interface CareerSkillSearchResponse {
  taxonomy: string
  language: string
  results: CareerSkillSearchResult[]
}

// ── Tenant / White-Label (Feature 85) ─────────────────────────────────────────

export interface TenantResponse {
  id: string
  slug: string
  name: string
  logo_url?: string | null
  primary_color?: string | null
  custom_domain?: string | null
  domain_verified: boolean
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
}

export interface TenantInvitationResponse {
  email: string
  role: string
  expires_in_seconds: number
  cohort_id?: string | null
  invite_preview_url?: string | null
  message: string
}

export interface TenantCohort {
  id: string
  name: string
  member_count: number
  resume_count: number
  created_at: string
}

export interface CohortSubmission {
  resume_id: string
  title: string
  student_user_id: string
  student_email: string
  student_name?: string | null
  started_at: string
  opened_at?: string | null
  opened_actor?: 'candidate' | null
  opened_source?: 'candidate_self' | null
  downloaded_at?: string | null
  downloaded_actor?: 'candidate' | null
  downloaded_source?: 'candidate_self' | null
}

export interface DomainVerifyResponse {
  domain: string
  verified: boolean
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
