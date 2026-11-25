/**
 * Typed REST API client for Latexy.
 * Handles job submission, state polling, result fetching, and PDF download.
 * All real-time updates come through the WebSocket (ws-client.ts).
 */

import { createTraceHeaders, trackBusinessEvent } from './telemetry'
import { captureAnalyticsEvent } from './analytics/posthog'
import type { ATSDeepAnalysis, RenderArtifact } from './event-types'
import { readEngineCapability } from './engine-capability'
import type { AdminPlanCatalogResponse, CatalogPlanUpdate, CatalogQuotaUpdate } from './plan-catalog'
import { fetchAcceptedArtifact } from './accepted-artifact-recovery'

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
  artifact?: RenderArtifact | null
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
  /** True when this result came from a draft-mode (typing preview) compile. */
  draft?: boolean
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
  /** Exact revision of the backend process answering this request, when the
   *  runtime carries a validated value. Null means unattested, not healthy. */
  commit_sha?: string | null
  /** "modal" | "production" | "local" - descriptive observability metadata. */
  deployment_target?: string
}

export interface BillingAvailability {
  provider?: 'dodo' | null
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
    apiDailyLimit?: number
    availabilityUnknown?: boolean
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
  content_revision?: number
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
  section_titles?: Record<string, string>
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

export interface BuilderCapabilitiesResponse {
  guided_builder_version: number
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

export interface AdminAnalyticsTimeseriesPoint {
  date: string
  new_users: number
  active_users: number
  compilations: number
  completed_compilations: number
  failed_compilations: number
  optimizations: number
  events: number
  revenue_inr: number
}

export interface AdminFeatureUsage {
  feature: string
  count: number
  last_used_at: string | null
}

export interface AdminRecentEvent {
  id: string
  action: string
  user_id: string | null
  metadata: Record<string, unknown>
  created_at: string | null
}

export interface AdminOperationsSummary {
  queued_jobs: number
  processing_jobs: number
  failed_jobs_24h: number
  completed_jobs_24h: number
  webhook_failures_24h: number
  active_users_24h: number
}

export type AdminAttentionSeverity = 'critical' | 'high' | 'low'

export interface AdminAttentionItem {
  key: string
  title: string
  severity: AdminAttentionSeverity
  owner: string
  count: number
  oldest_at: string | null
  href: string
  detail: string
  source_status: 'ok' | 'partial' | 'unavailable'
  next_expiry_at?: string | null
  days_until_expiry?: number | null
  metadata_status?: 'complete' | 'partial' | 'unknown'
}

export interface AdminAttentionSource {
  key: string
  status: 'ok' | 'partial' | 'unavailable'
  count?: number
  detail?: string
  metadata_status?: 'complete' | 'partial' | 'unknown'
  domain_expiring?: number
  certificate_expiring?: number
  unverified?: number
  unknown_domain_expiry?: number
  unknown_certificate_expiry?: number
}

export interface AdminAttentionResponse {
  generated_at: string
  overall: 'attention' | 'clear'
  partial: boolean
  items: AdminAttentionItem[]
  sources: AdminAttentionSource[]
}

export type AdminOperationsStatus = 'healthy' | 'degraded' | 'unhealthy'

export interface AdminOperationsHealthSection {
  status: AdminOperationsStatus
  observed_at: string
  detail?: string
  [metric: string]: string | number | boolean | null | undefined
}

export interface AdminWorkerHealthComponent {
  worker_id: string
  kind: 'celery' | 'modal'
  status: AdminOperationsStatus
  last_seen: string
  age_seconds: number
  cpu_percent: number | null
  memory_percent: number | null
  memory_mb: number | null
  queues: string[]
  missing_metrics: boolean
  missing_queue_ownership: boolean
}

export interface AdminWorkerProviderLink {
  name: string
  console_url: string
}

export interface AdminWorkerHealth {
  status: AdminOperationsStatus
  observed_at: string
  last_check_at: string
  read_ok: boolean
  detail?: string | null
  stale_after_seconds: number
  ttl_seconds: number
  active_workers: number
  stale_workers: number
  missing_metrics: number
  components: AdminWorkerHealthComponent[]
  queue_ownership: Record<string, number>
  unowned_queues: string[]
  providers: AdminWorkerProviderLink[]
}

export interface AdminOperationsHealthResponse {
  generated_at: string
  status: AdminOperationsStatus
  sections: Record<string, AdminOperationsHealthSection>
  workers?: AdminWorkerHealth
}

export type AdminQueueStatus = 'healthy' | 'backlogged' | 'stale'

export interface AdminQueueThroughputPoint {
  sampled_at: string
  depth: number
  oldest_age_seconds: number | null
  enqueue_rate_per_minute: number | null
  completion_rate_per_minute: number | null
}

export interface AdminQueueMetricsEntry {
  queue: string
  depth: number
  oldest_age_seconds: number | null
  enqueue_rate_per_minute: number | null
  completion_rate_per_minute: number | null
  sampled_at: string
  status: AdminQueueStatus
}

export interface AdminQueueMetricsResponse {
  generated_at: string
  queues: AdminQueueMetricsEntry[]
  throughput: Record<string, AdminQueueThroughputPoint[]>
}

export type AdminStuckJobAction = 'retry' | 'cancel' | 'fence'

export interface AdminStuckJobItem {
  job_id: string
  job_type: string
  owner: string | null
  owner_user_id: string | null
  owner_kind: 'user' | 'anonymous'
  resume_id: string | null
  queue: string
  status: string
  stage: string | null
  finalization_state: string | null
  compilation_status: string | null
  created_at: string | null
  updated_at: string | null
  age: string
  age_seconds: number
  heartbeat_age_seconds: number | null
  lease_expires_at: string | null
  lease_expired: boolean | null
  lease_active: boolean
  lease_state: 'none' | 'missing' | 'active' | 'expired'
  worker: string | null
  worker_epoch: number | null
  cancel_requested: boolean
  reason_code: string
  reason: string
  terminal: boolean
  retry_supported: boolean
  recommended_actions: AdminStuckJobAction[]
  source: 'finalization' | 'compilation' | 'finalization+compilation'
}

export interface AdminStuckJobList {
  generated_at: string
  min_age_minutes: number
  stale_after_seconds: number
  total: number
  truncated: boolean
  summary: {
    total: number
    queued: number
    processing: number
    stale: number
    oldest_age_seconds: number
    retry_supported: number
  }
  items: AdminStuckJobItem[]
}

export interface AdminStuckJobActionResponse {
  success: boolean
  action: AdminStuckJobAction
  job_id: string
  changed: boolean
  idempotent: boolean
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  reason: string | null
  audit_id: string | null
  new_job_id: string | null
  dispatch_status: string | null
}

export interface AdminAlert {
  id: string
  kind: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  owner: string
  title: string
  dedupe_key: string
  payload: Record<string, unknown>
  runbook_url: string | null
  state: 'open' | 'acknowledged' | 'snoozed' | 'resolved'
  occurrence_count: number
  first_seen_at: string | null
  last_seen_at: string | null
  acknowledged_by: string | null
  acknowledged_at: string | null
  acknowledgement_note: string | null
  snoozed_by: string | null
  snoozed_at: string | null
  snooze_until: string | null
  resolved_at: string | null
  resolution: string | null
  created_at: string | null
  updated_at: string | null
}

export interface AdminAlertList {
  items: AdminAlert[]
  total: number
  limit: number
  offset: number
}

export interface AdminKpiTrendPoint {
  date: string
  value: number
}

export interface AdminKpiTrend {
  key: string
  label: string
  unit: 'count' | 'currency' | 'percent'
  current: number
  previous: number
  absolute_delta: number
  percent_delta: number | null
  baseline_zero: boolean
  sparkline: AdminKpiTrendPoint[]
}

export interface AdminAnalyticsOverviewResponse {
  period_days: number
  system: {
    period_days: number
    total_users: number
    new_users: number
    total_compilations: number
    successful_compilations: number
    success_rate: number
    total_optimizations: number
    active_subscriptions: number
    total_revenue_inr: number
    trial_users: number
    conversion_rate: number
    real_time_metrics: Record<string, unknown>
  }
  conversion_funnel: {
    period_days: number
    funnel_steps: Record<string, number>
    conversion_rates: Record<string, number>
  }
  timeseries: AdminAnalyticsTimeseriesPoint[]
  top_features: AdminFeatureUsage[]
  recent_events: AdminRecentEvent[]
  operations: AdminOperationsSummary
  kpi_trends: AdminKpiTrend[]
  generated_at: string
}

export interface AdminCompileLatencyBucket {
  value: string
  label: string
  samples: number
  p50_seconds: number | null
  p95_seconds: number | null
  p99_seconds: number | null
  mean_seconds: number | null
  max_seconds: number | null
  sparse: boolean
  sample_status: 'ok' | 'insufficient_samples'
}

export interface AdminCompileLatencySlowestBucket extends AdminCompileLatencyBucket {
  dimension: 'plan' | 'compiler' | 'template'
}

export interface AdminCompileLatencyResponse {
  days: number
  window: { start: string; end: string }
  filters: { plan: string | null; compiler: string | null; template: string | null }
  duration_unit: 'seconds'
  sparse_threshold: number
  slowest_limit: number
  overall: Omit<AdminCompileLatencyBucket, 'value' | 'label'>
  by_plan: AdminCompileLatencyBucket[]
  by_compiler: AdminCompileLatencyBucket[]
  by_template: AdminCompileLatencyBucket[]
  slowest: AdminCompileLatencySlowestBucket[]
  missing_dimensions: { plan: number; compiler: number; template: number }
  totals: {
    completed_compilations: number
    timed_compilations: number
    missing_dimension_fields: number
  }
  generated_at: string
}

export type AdminCompileErrorClassKey =
  | 'syntax'
  | 'missing_package'
  | 'timeout'
  | 'engine'
  | 'storage'
  | 'pdf_limit'
  | 'unknown'

export interface AdminCompileErrorTemplate {
  template_id: string
  template_name: string | null
  count: number
  latest_at: string | null
  href: string
  sparse: boolean
}

export interface AdminCompileErrorBucket {
  error_class: AdminCompileErrorClassKey
  label: string
  count: number
  share: number
  latest_at: string | null
  affected_templates: AdminCompileErrorTemplate[]
  unattributed_templates: number
  sparse: boolean
}

export interface AdminCompileErrorTrendPoint {
  date: string
  failed_compilations: number
  by_class: Partial<Record<AdminCompileErrorClassKey, number>>
}

export interface AdminCompileErrorsResponse {
  days: number
  window: { start: string; end: string }
  filters: {
    plan: string | null
    compiler: string | null
    template: string | null
    error_class: AdminCompileErrorClassKey | null
  }
  classes: Array<{
    error_class: AdminCompileErrorClassKey
    label: string
    count: number
    share: number
    sparse: boolean
  }>
  top_errors: AdminCompileErrorBucket[]
  trend: AdminCompileErrorTrendPoint[]
  totals: {
    failed_compilations: number
    classified_compilations: number
    unknown_compilations: number
    class_total: number
    reconciled: boolean
    classes_with_errors: number
    templates_with_errors: number
  }
  suppression: {
    minimum_sample_size: number
    user_dimension_included: false
    detail: string
  }
  generated_at: string
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
  parent_key?: string | null
  inventory_id?: string | null
  control_kind?: 'parent' | 'product' | 'subfeature'
  product_inventory_id?: string | null
  always_on_reason?: string | null
}

/** Full admin entitlements state from GET /admin/entitlements. */
export interface AdminEntitlementsState {
  registry: EntitlementFeatureDef[]
  kill_switches: Record<string, boolean>
  matrix: Record<string, Record<string, boolean>>
  plan_families: string[]
  plan_keys?: string[]
  plan_family_by_key?: Record<string, string>
  roles?: EntitlementRole[]
  role_matrix?: Record<string, Record<string, boolean>>
}

export type UserRole = 'user' | 'support' | 'admin'
export type EntitlementRole = 'anonymous' | UserRole

export interface AdminUser {
  id: string
  email: string
  name: string | null
  /** Always true on list responses; reveal one field through the audited endpoint. */
  pii_masked: boolean
  role: UserRole
  subscription_plan: string | null
  email_verified: boolean
  created_at: string
}

export interface AdminUsersResponse {
  users: AdminUser[]
  total: number
}

export interface AdminBillingPlanMix {
  plan_id: string
  subscriptions: number
  mrr: number
  mrr_minor: number
  interval: string
  revenue: number
  revenue_minor: number
  refunded: number
  refunded_minor: number
  net_revenue: number
  net_revenue_minor: number
  payments_count: number
  refunds_count: number
  share_percent: number
}

export interface AdminBillingMrrInterval {
  interval: string
  subscriptions: number
  mrr_minor: number
  mrr: number
}

export interface AdminBillingMrrNormalization {
  basis: string
  annual_divisor: number
  weekly_weeks_per_month: number
  lifetime_policy: string
  active_subscriptions: number
  recurring_subscriptions: number
  by_interval: AdminBillingMrrInterval[]
}

export interface AdminBillingRevenuePoint {
  bucket: string
  label: string
  gross_revenue_minor: number
  refunds_minor: number
  chargebacks_minor: number
  net_revenue_minor: number
  net_revenue_after_chargebacks_minor: number
  payments_count: number
  refunds_count: number
  chargebacks_count: number
}

export interface AdminBillingRefundStatus {
  status: string
  count: number
  amount_minor: number
}

export interface AdminBillingRecentRefund {
  id: string
  payment_id: string
  amount_minor: number
  currency: string
  status: string
  created_at: string | null
}

export interface AdminBillingRefundView {
  currency: string
  total_minor: number
  total: number
  count: number
  succeeded_minor: number
  succeeded: number
  succeeded_count: number
  failed_minor: number
  failed_count: number
  pending_minor: number
  pending_count: number
  by_status: AdminBillingRefundStatus[]
  recent: AdminBillingRecentRefund[]
}

export interface AdminBillingChargebackItem {
  id: string
  event_type: string
  status: string
  amount_minor: number | null
  currency: string | null
  payment_id: string | null
  payment_linked: boolean
  bucket: string
  event_at: string | null
  received_at: string | null
}

export interface AdminBillingChargebackStatus {
  status: string
  count: number
  amount_minor: number
  events: number
}

export interface AdminBillingChargebackView {
  currency: string
  total_minor: number
  total: number
  count: number
  events_count: number
  open_count: number
  resolved_count: number
  lost_count: number
  won_count: number
  open_minor: number
  resolved_minor: number
  lost_minor: number
  won_minor: number
  unlinked_count: number
  amount_unavailable_count: number
  by_status: AdminBillingChargebackStatus[]
  items: AdminBillingChargebackItem[]
}

export interface AdminBillingReconciliationCheck {
  key: string
  label: string
  ok: boolean
  expected_minor: number
  actual_minor: number
  difference_minor: number
}

export interface AdminBillingRevenueReconciliation {
  currency: string
  gross_from_payments_minor: number
  refunded_from_payment_refunds_minor: number
  net_revenue_minor: number
  expected_net_minor: number
  difference_minor: number
  balanced: boolean
  payments_count: number
  refunds_count: number
  chargebacks_from_events_minor: number
  net_after_chargebacks_minor: number
  plan_mix_attributed_revenue_minor: number
  plan_mix_attributed_refunds_minor: number
  plan_mix_attributed_net_minor: number
  plan_mix_revenue_difference_minor: number
  test_mode_excluded: boolean
  test_mode_policy: string
  checks: AdminBillingReconciliationCheck[]
}

export interface AdminRefundRequest {
  id: string
  payment_id: string
  status: 'pending' | 'approved' | 'rejected' | 'executing' | 'executed' | 'failed' | 'cancelled'
  amount: number | null
  currency: string | null
  provider_item_id: string | null
  tax_inclusive: boolean
  reason: string
  decision_note: string | null
  requested_by: string
  requested_email: string | null
  approved_by: string | null
  approved_email: string | null
  executed_by: string | null
  provider_refund_id: string | null
  last_error: string | null
  requested_at: string | null
  decided_at: string | null
  executed_at: string | null
  updated_at: string | null
}

export interface AdminBillingSummary {
  period_days: number
  period_start: string
  period_end: string
  generated_at: string
  currency: string
  granularity: 'day' | 'month'
  mrr: number
  arr: number
  mrr_minor: number
  arr_minor: number
  arpu: number
  arpu_minor: number
  active_subscriptions: number
  active_recurring_subscriptions: number
  past_due_subscriptions: number
  gross_revenue: number
  refunded: number
  net_revenue: number
  chargebacks: number
  net_revenue_after_chargebacks: number
  gross_revenue_minor: number
  refunded_minor: number
  net_revenue_minor: number
  chargebacks_minor: number
  chargebacks_count: number
  net_revenue_after_chargebacks_minor: number
  payments_count: number
  refunds_count: number
  open_refund_requests: number
  unacknowledged_webhook_failures: number
  webhooks_24h: number
  webhook_failures_24h: number
  mrr_normalization: AdminBillingMrrNormalization
  revenue_series: AdminBillingRevenuePoint[]
  refund_view: AdminBillingRefundView
  chargeback_view: AdminBillingChargebackView
  reconciliation: AdminBillingRevenueReconciliation
  plan_mix: AdminBillingPlanMix[]
  recent_refund_requests: AdminRefundRequest[]
}

export interface AdminCheckoutFunnelStep {
  key: 'checkout_started' | 'checkout_completed' | 'checkout_paid'
  label: string
  count: number
  from_previous: number
  from_start: number
  drop_off: number
  drop_off_pct: number
}

export interface AdminCheckoutFailureBucket {
  bucket: 'provider_declined' | 'validation' | 'abandoned' | 'unavailable' | 'unknown'
  label: string
  description: string
  count: number
  share: number
}

export interface AdminCheckoutFunnelPlan {
  plan_id: string
  started: number
  completed: number
  paid: number
  failed: number
  conversion_pct: number
}

export interface AdminCheckoutFunnelPaidAmount {
  currency: string
  amount_minor: number
  checkouts: number
}

export interface AdminCheckoutFunnelReconciliation {
  started: number
  completed: number
  paid: number
  failed: number
  completed_not_paid: number
  failure_bucket_sum: number
  started_equals_paid_plus_failed: boolean
  completed_at_least_paid: boolean
  failure_buckets_match: boolean
}

export interface AdminCheckoutFunnel {
  range_days: number
  period_start: string
  period_end: string
  generated_at: string
  billing_mode: string
  currency: string
  minimum_segment_size: number
  abandonment_hours: number
  steps: AdminCheckoutFunnelStep[]
  conversion: {
    started_to_completed: number
    completed_to_paid: number
    started_to_paid: number
  }
  failures: {
    total: number
    buckets: AdminCheckoutFailureBucket[]
  }
  reconciliation: AdminCheckoutFunnelReconciliation
  paid_amounts: AdminCheckoutFunnelPaidAmount[]
  by_plan: AdminCheckoutFunnelPlan[]
  suppressed_segments: number
  excluded_other_mode_attempts: number
  definitions: Record<string, string>
  notes: string[]
}

export interface AdminSubscriptionSummary {
  active_at_start: number
  active_at_end: number
  plan_mix_total: number
  upgrades: number
  downgrades: number
  lateral_moves: number
  movement_total: number
  cancellations: number
  cancellation_scheduled: number
  expired: number
  payment_failed: number
  refunded: number
  churn_count: number
  churn_rate: number | null
  new_paid: number
  reactivations: number
  mrr_minor: number
  mrr: number
}

export interface AdminSubscriptionPlanMix {
  plan_id: string
  subscriptions: number
  users: number
  share_pct: number
  mrr_minor: number
  mrr: number
  currency: string
}

export interface AdminSubscriptionMovement {
  direction: 'upgrade' | 'downgrade' | 'lateral'
  from_plan: string
  to_plan: string
  count: number
  users: number
}

export interface AdminSubscriptionChurn {
  reason: string
  count: number
  users: number
}

export interface AdminSubscriptionCohortPlanMix {
  plan_id: string
  subscriptions: number
  currency: string
}

export interface AdminSubscriptionCohort extends AdminSubscriptionSummary {
  cohort: string
  users: number
  plan_mix: AdminSubscriptionCohortPlanMix[]
}

export interface AdminSubscriptionAnalyticsResponse {
  period_days: number
  period_start: string
  period_end: string
  currency: string
  minor_unit: string
  minimum_cohort_size: number
  filters: {
    days: number
    start: string
    end: string
    signup_month: string | null
    signup_from: string | null
    signup_to: string | null
    plan: string | null
    timezone: string
  }
  available_signup_months: Array<{ month: string; users: number }>
  summary: AdminSubscriptionSummary
  plan_mix: AdminSubscriptionPlanMix[]
  movements: AdminSubscriptionMovement[]
  churn: AdminSubscriptionChurn[]
  cohorts: AdminSubscriptionCohort[]
  suppressed: boolean
  suppressed_cohorts: number
  reconciliation: {
    history_rows: number
    backfill_rows: number
    movement_total_reconciles: boolean
    churn_reconciles: boolean
    plan_mix_total_matches_active_at_end: boolean
    current_active_subscriptions: number
    plan_mix_matches_current: boolean
    checks: Array<{
      key: string
      label: string
      ok: boolean
      detail: string
    }>
  }
  generated_at: string
}

export interface AdminBillingWebhook {
  id: string
  provider: string
  event_id: string
  event_type: string
  event_resource_id: string | null
  status: string
  attempts: number
  last_error: string | null
  event_at: string | null
  received_at: string | null
  processed_at: string | null
  acknowledged_at: string | null
  acknowledged_by: string | null
  acknowledgement_note: string | null
  reconcile_attempts: number
  last_reconcile_at: string | null
  last_reconcile_error: string | null
  last_reconcile_outcome: string | null
  local_link: {
    linked: boolean
    local_type: string
    local_id: string | null
    subscription_id?: string | null
    user_id?: string | null
    payment_id?: string | null
  }
}

export type AdminBillingWebhookMutation = Omit<AdminBillingWebhook, 'local_link'>

export interface AdminBillingWebhookList {
  items: AdminBillingWebhook[]
  total: number
  limit: number
  offset: number
}

export interface AdminBillingReconciliation extends AdminBillingWebhook {
  link_status: string | null
  amount_minor: number | null
  currency: string | null
  age_seconds: number | null
  age_hours: number | null
  mismatch_reason: string
  suggested_action: string
  can_replay: boolean
}

export interface AdminBillingReconciliationList {
  items: AdminBillingReconciliation[]
  total: number
  limit: number
  offset: number
}

export interface AdminRefundList {
  items: AdminRefundRequest[]
  total: number
  limit: number
  offset: number
}

export interface AdminUser360 {
  user: {
    id: string
    email: string | null
    name: string | null
    pii_masked: boolean
    role: UserRole
    subscription_plan: string | null
    subscription_status: string | null
    email_verified: boolean
    two_factor_enabled: boolean
    trial_used: boolean
    created_at: string | null
    updated_at: string | null
    public_username: string | null
    portfolio_enabled: boolean
    default_tenant_id: string | null
  }
  activation: {
    has_resume: boolean
    has_compile: boolean
    has_optimization: boolean
    has_export: boolean
    has_paid: boolean
    last_activity_at: string | null
  }
  usage: {
    events_30d: number
    actions: Array<{ action: string; count: number; last_at: string | null }>
    recent_events: Array<{ action: string; resource_type: string | null; created_at: string | null }>
  }
  production: {
    resumes: number
    recent_resumes: Array<{
      id: string
      title: string
      document_type: string | null
      created_at: string | null
      updated_at: string | null
    }>
    compilations: number
    successful_compilations: number
    failed_compilations: number
    last_compilation_at: string | null
    optimizations: number
    last_optimization_at: string | null
  }
  integrations: Record<string, boolean>
  billing: {
    subscriptions: Array<Record<string, unknown>>
    payments: Array<{
      id: string
      provider_payment_id: string | null
      amount: number
      currency: string
      status: string
      payment_method: string | null
      created_at: string | null
    }>
    refunds: Array<Record<string, unknown>>
    refund_requests: Array<{
      id: string
      payment_id: string
      status: string
      amount: number | null
      currency: string | null
      requested_at: string | null
      decided_at: string | null
      executed_at: string | null
    }>
  }
  security: {
    sessions: Array<{
      id: string
      created_at: string | null
      expires_at: string | null
      user_agent: string | null
    }>
    session_count: number
    passkey_count: number
    passkeys: Array<{
      id: string
      name: string | null
      device_type: string | null
      backed_up: boolean
      created_at: string | null
    }>
    byok_keys: Array<{
      id: string
      provider: string
      name: string | null
      is_active: boolean
      created_at: string | null
    }>
    developer_keys: Array<{
      id: string
      prefix: string
      name: string | null
      is_active: boolean
      request_count: number
      last_used_at: string | null
    }>
  }
  entitlements: {
    effective: Record<string, boolean>
    overrides: Record<string, { enabled: boolean }>
    available_features: Array<{
      key: string
      label: string
      category: string
      parent_key: string | null
    }>
    available: boolean
  }
  quota: AdminUserQuotaSnapshot
  trial: {
    trial_used: boolean
    eligible: boolean
    extended_until: string | null
    updated_at: string | null
    updated_by: string | null
    source: string
  }
  recent_admin_actions: AdminAuditEntry[]
}

export interface AdminCredentialRevokeResponse {
  kind: 'session' | 'passkey' | 'byok' | 'developer'
  item_id: string
  revoked: boolean
  already_revoked: boolean
}

export interface AdminUserQuotaDimension {
  used: number | null
  limit: number | null
  policy_available: boolean
  window: 'day' | 'month'
  period: string
  resets_at: string
}

export interface AdminUserQuotaSnapshot {
  period: string
  resets_at: string
  policy_available: boolean
  authority_available: boolean
  dimensions: Record<string, AdminUserQuotaDimension>
}

export interface AdminUserActionEffective {
  feature_key: string
  changed: boolean
  override: boolean
  before: { override: boolean | null }
  after: { override: boolean | null }
  effective: boolean
  available: boolean
  features: Record<string, boolean>
  entitlement?: { features: Record<string, boolean>; available: boolean }
  quota?: AdminUserQuotaSnapshot
}

export interface AdminUserTrialActionResult {
  changed: boolean
  days?: number
  device_trials_reset: number
  before: AdminUser360['trial']
  after: AdminUser360['trial']
  trial: AdminUser360['trial']
}

export interface AdminAuditEntry {
  id: string
  actor_user_id: string | null
  actor_email: string | null
  action: string
  target_type: string
  target_id: string | null
  reason: string | null
  request_id: string | null
  ip_address: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  created_at: string | null
}

export interface AdminAuditFilters {
  actor_user_id: string | null
  action: string | null
  target_type: string | null
  target_id: string | null
  created_after: string | null
  created_before: string | null
}

export interface AdminAuditList {
  items: AdminAuditEntry[]
  total: number
  limit: number
  next_cursor: string | null
  has_more: boolean
  filters: AdminAuditFilters
}

export interface AdminChangeHistoryFilters {
  key: string | null
  target_id: string | null
  actor_user_id: string | null
  action: string | null
  created_after: string | null
  created_before: string | null
}

export interface AdminChangeHistoryList {
  items: AdminAuditEntry[]
  total: number
  limit: number
  next_cursor: string | null
  has_more: boolean
  read_only: true
  target_types: string[]
  filters: AdminChangeHistoryFilters
}

// ---------------------------------------------------------------- //
//  GDPR data-subject workflow                                      //
// ---------------------------------------------------------------- //

export type GdprRequestType = 'export' | 'deletion'
export type GdprRequestStatus =
  | 'pending'
  | 'legal_review'
  | 'approved'
  | 'processing'
  | 'ready'
  | 'completed'
  | 'failed'
  | 'rejected'
  | 'cancelled'
  | 'blocked'
  | 'expired'

export interface GdprRetentionException {
  category: string
  tables: string[]
  reason: string
  legal_basis: string
}

export interface GdprTableResult {
  table: string
  step: string
  action: 'delete' | 'update' | 'anonymize' | 'retain'
  status: 'completed' | 'failed' | 'retained'
  rows_affected: number
  description?: string
  error_code?: string
  reason?: string
  category?: string
}

export interface GdprRequestSummary {
  id: string
  request_type: GdprRequestType
  status: GdprRequestStatus
  legal_review_status: 'not_required' | 'pending' | 'approved' | 'rejected'
  identity_verified: boolean
  reauthenticated_at: string | null
  confirmed_at: string | null
  legal_reviewed_at: string | null
  review_note: string | null
  legal_hold_blocked: boolean
  export_expires_at: string | null
  export_downloaded_at: string | null
  export_available: boolean
  failure_code: string | null
  failure_detail: string | null
  attempts: number
  failed_tables: string[]
  table_results: GdprTableResult[]
  retention_exceptions: GdprRetentionException[]
  created_at: string | null
  updated_at: string | null
  finished_at: string | null
  can_cancel: boolean
  // Admin list fields.
  user_id?: string | null
  user_email_masked?: string | null
  legal_reviewed_by?: string | null
  legal_hold_active?: boolean
}

export interface GdprPolicy {
  deletion_confirmation: string
  export_ttl_minutes: number
  reauth_max_age_minutes: number
  retention_exceptions: GdprRetentionException[]
  export_scope: { included: string[]; excluded: string[] }
}

export interface GdprExportResponse {
  request: GdprRequestSummary
  download_token: string
  download_path: string
  download_token_header: string
  expires_at: string | null
  reissued: boolean
}

export interface GdprDeletionResponse {
  request: GdprRequestSummary
  created: boolean
  retention_exceptions: GdprRetentionException[]
}

export interface GdprRequestList {
  items: GdprRequestSummary[]
  total: number
  limit?: number
  offset?: number
}

export interface GdprLegalHold {
  id: string
  user_id: string
  user_email_masked: string | null
  active: boolean
  reason: string
  placed_by: string
  placed_at: string | null
  released_by: string | null
  released_at: string | null
  release_reason: string | null
}

export interface GdprLegalHoldList {
  items: GdprLegalHold[]
  total: number
}

export interface AdminActivationStep {
  key: string
  label: string
  count: number
  from_previous: number
  from_signup: number
  drop_off?: number
  drop_off_pct?: number
  median_seconds_from_previous?: number | null
  median_days_from_previous?: number | null
}

export interface AdminActivationSegment {
  label: string
  users: number
  steps: Record<string, number>
  windows?: Record<string, Record<string, number>>
}

export interface AdminActivationWindow {
  window_days: number
  cohort_size: number
  steps: AdminActivationStep[]
}

export interface AdminActivationResponse {
  period_days: number
  activation_window_days: number
  cohort_size: number
  steps: AdminActivationStep[]
  windows?: Record<string, AdminActivationWindow>
  by_plan: AdminActivationSegment[]
  by_provider: AdminActivationSegment[]
  by_signup_cohort?: AdminActivationSegment[]
  signup_funnel?: AdminSignupFunnel
  suppressed_segments?: Record<string, number>
  minimum_segment_size?: number
  milestone_definitions?: Array<{
    key: string
    label: string
    source: string
    definition: string
  }>
  reconciliation?: Record<string, { source: string; users: number }>
  generated_at: string
}

export interface AdminLandingConversionRow {
  // Grouped rows only carry the labels for the dimensions they group by.
  page_key?: string | null
  page_label?: string
  missing_page_key?: boolean
  experiment?: string | null
  experiment_label?: string
  missing_experiment?: boolean
  variant?: string | null
  variant_label?: string
  missing_variant?: boolean
  device_class?: 'mobile' | 'tablet' | 'desktop' | 'unknown'
  device_label?: string
  visits: number
  trial_starts: number
  registrations: number
  subscriptions: number
  sample_size: number
  conversion_rate: number
  trial_conversion_rate: number
  subscription_conversion_rate: number
}

export interface AdminLandingConversionResponse {
  days: number
  period: { start: string; end: string; timezone: string }
  minimum_segment_size: number
  summary: {
    period_days: number
    funnel_steps: {
      landing_visits: number
      trial_starts: number
      registrations: number
      subscriptions: number
    }
    conversion_rates: {
      landing_to_trial: number
      trial_to_registration: number
      registration_to_subscription: number
      overall_conversion: number
    }
    sample_sizes: {
      landing_visits: number
      trial_starts: number
      registrations: number
      subscriptions: number
    }
    attribution: {
      model: string
      attributed_trial_starts: number
      attributed_registrations: number
      unattributed_trial_starts: number
      unattributed_registrations: number
      registration_coverage_pct: number
      description: string
    }
  }
  by_device: AdminLandingConversionRow[]
  by_page: AdminLandingConversionRow[]
  by_page_variant: AdminLandingConversionRow[]
  by_page_variant_device: AdminLandingConversionRow[]
  suppressed_cells: number
  truncated_cells: number
  supported_page_keys: string[]
  variant_labels: {
    missing: string
    missing_experiment: string
    missing_page: string
    unknown_device: string
  }
  notes: string[]
  generated_at: string
}

export type SignupAuthProvider = 'email' | 'google' | 'github' | 'oidc' | 'passkey' | 'unknown'
export type SignupOAuthFailureCode =
  | 'access_denied'
  | 'account_not_linked'
  | 'callback_failed'
  | 'provider_error'
  | 'state_mismatch'
  | 'unknown'

export interface AdminSignupFunnelStep {
  key: 'signup_started' | 'signup_completed' | 'email_verified'
  label: string
  count: number
  from_previous: number | null
  from_start: number
  median_seconds: number | null
  median_days: number | null
}

export interface AdminSignupFunnelProvider {
  label: string
  provider: string
  provider_label: string
  users: number
  started: number
  completed: number
  verified: number
  verification_rate: number
  conversion_start_to_complete: number
  conversion_complete_to_verified: number
  median_seconds_to_verify: number | null
  median_days_to_verify: number | null
}

export interface AdminSignupFunnelFailure {
  label: string
  provider: string
  provider_label: string
  count: number
}

export interface AdminSignupFunnel {
  period_days: number
  cohort_size: number
  started: number
  completed: number
  verified: number
  verification_rate: number
  conversion_start_to_complete: number
  conversion_complete_to_verified: number
  median_seconds_to_verify: number | null
  median_days_to_verify: number | null
  steps: AdminSignupFunnelStep[]
  by_provider: AdminSignupFunnelProvider[]
  oauth_failures: {
    total: number
    by_provider: AdminSignupFunnelFailure[]
    by_code: Array<{ code: string; count: number }>
  }
  suppressed_segments?: Record<string, number>
  minimum_segment_size?: number
  provider_labels?: Record<string, string>
  started_by_provider?: Array<{ label: string; provider: string; count: number }>
  generated_at: string
}

export interface SignupMilestonesResponse {
  provider: SignupAuthProvider
  email_verified: boolean
  recorded: string[]
}

export interface AdminTrafficSourceRow {
  label: string
  sessions: number
  visitors: number
  signups: number | null
  paid_users: number | null
  signup_conversion: number | null
  paid_conversion: number | null
  suppressed_cells: string[]
}

export interface AdminTrafficSourceTotals {
  sessions: number
  visitors: number
  signups: number
  paid_users: number
  signup_conversion: number
  paid_conversion: number
}

export interface AdminTrafficSourcesResponse {
  period: { start: string; end: string; days: number }
  minimum_cohort_size: number
  attribution_window_days: number
  totals: AdminTrafficSourceTotals
  unattributed_signups: number
  by_source: AdminTrafficSourceRow[]
  by_medium: AdminTrafficSourceRow[]
  by_campaign: AdminTrafficSourceRow[]
  by_referrer: AdminTrafficSourceRow[]
  suppressed: Record<string, number>
  truncated: Record<string, number>
  notes?: Record<string, string>
  generated_at: string
}

export interface AdminTrialAttributionRow {
  label: string
  trial_starts: number
  signups: number | null
  paid_users: number | null
  trial_to_signup_pct: number | null
  trial_to_paid_pct: number | null
  signup_to_paid_pct: number | null
  median_days_to_signup: number | null
  median_days_to_paid: number | null
  paid_within_7d: number | null
  paid_within_30d: number | null
  paid_within_90d: number | null
  conversion_within_7d_pct: number | null
  conversion_within_30d_pct: number | null
  conversion_within_90d_pct: number | null
  suppressed_cells: string[]
}

export interface AdminTrialAttributionResponse {
  period: { start: string; end: string; days: number }
  minimum_cohort_size: number
  conversion_windows_days: number[]
  totals: {
    trial_starts: number
    linked_trials: number
    unlinked_trials: number
    anonymous_source_trials: number
    signups: number | null
    paid_users: number | null
    trial_to_signup_pct: number | null
    trial_to_paid_pct: number | null
    signup_to_paid_pct: number | null
    median_days_to_signup: number | null
    median_days_to_paid: number | null
    paid_within_7d: number | null
    paid_within_30d: number | null
    paid_within_90d: number | null
    conversion_within_7d_pct: number | null
    conversion_within_30d_pct: number | null
    conversion_within_90d_pct: number | null
    source_attributed_trials: number
    linkage_coverage_pct: number
    source_coverage_pct: number
  }
  reconciliation: {
    period_trial_starts: number
    linked_trials: number
    unlinked_trials: number
    anonymous_trials: number
    source_attributed_trials: number
    unattributed_trials: number
    cohort_signups: number
    cohort_paid_users: number
    subscriptions_linked_to_cohort: number
    period_signups: number
    period_paid_subscriptions: number
    period_paid_users: number
    unattributed_signups: number
    unattributed_paid_users: number
    deleted_user_attributions: number
  }
  by_source: AdminTrialAttributionRow[]
  by_plan: AdminTrialAttributionRow[]
  by_signup_month: AdminTrialAttributionRow[]
  suppressed: Record<string, number>
  truncated: Record<string, number>
  notes: string[]
  generated_at: string
}

export interface AdminRetentionCell {
  count: number
  eligible: number
  numerator: number
  denominator: number
  cohort_size: number
  rate: number | null
}

export interface AdminRetentionPoint {
  cohort: string
  cohort_size: number
  numerator: number
  denominator: number
  rate: number | null
}

export interface AdminRetentionWeeklyPoint extends AdminRetentionCell {
  week: number
}

export interface AdminRetentionRow {
  week_start?: string
  signup_month?: string
  cohort_size: number
  d1: AdminRetentionCell
  d7: AdminRetentionCell
  d30: AdminRetentionCell
  w1: AdminRetentionCell
  w2_plus: AdminRetentionCell
  weekly: AdminRetentionWeeklyPoint[]
}

export interface AdminRetentionResponse {
  weeks: number
  signup_month?: string | null
  available_signup_months?: Array<{ month: string; users: number }>
  cohorts: AdminRetentionRow[]
  monthly?: AdminRetentionRow[]
  curves?: {
    d1: AdminRetentionPoint[]
    d7: AdminRetentionPoint[]
    d30: AdminRetentionPoint[]
    w1: AdminRetentionPoint[]
    w2_plus: AdminRetentionPoint[]
    weekly: Array<AdminRetentionWeeklyPoint & { numerator: number; denominator: number; cohort_size: number; rate: number | null }>
  }
  overall: {
    cohort_size: number
    d1: AdminRetentionCell
    d7: AdminRetentionCell
    d30: AdminRetentionCell
    w1?: AdminRetentionCell
    w2_plus?: AdminRetentionCell
    weekly?: AdminRetentionWeeklyPoint[]
  }
  minimum_cohort_size: number
  hidden_weekly_cohorts?: number
  hidden_monthly_cohorts?: number
  activity_definition?: string
  period?: { start: string; end: string }
  generated_at: string
}

export interface AdminAiCostResponse {
  period_days: number
  generated_at: string
  filters: { plan: string | null; feature: string | null; persona: string | null }
  estimated: boolean
  price_note: string
  cost_currency: string
  cost_minor_unit: string
  revenue_currency: string
  revenue_minor_unit: string
  pricing_version: string
  pricing: {
    version: string
    schema_version: string
    source: string
    currency: string
    minor_unit: string
    unit: string
    blended_for_total_tokens: boolean
    fallback_per_million_usd: number
    models: Array<{
      provider: string
      model: string
      input_per_million_usd: number
      output_per_million_usd: number
      blended_per_million_usd: number
    }>
  }
  usd_inr_rate: number
  monthly_spend_cap_usd: number | null
  monthly_soft_spend_cap_usd: number | null
  total_tokens: number
  total_cost_usd: number
  total_cost_usd_minor: number
  total_cost_inr: number
  total_cost_inr_minor: number
  total_revenue_inr: number
  total_revenue_inr_minor: number
  gross_margin_inr: number
  gross_margin_inr_minor: number
  optimizations: number
  estimated_runs: number
  unknown_pricing_runs: number
  pricing_complete: boolean
  by_model: Array<{
    provider: string
    model: string
    runs: number
    tokens: number
    cost_usd: number
    cost_usd_minor: number
    fallback_price?: boolean
    pricing_status: string
    estimated: boolean
    estimated_runs: number
    unknown_pricing_runs: number
    unknown_pricing: boolean
  }>
  unknown_pricing: {
    runs: number
    tokens: number
    cost_usd: number
    cost_usd_minor: number
    models: Array<{
      provider: string
      model: string
      runs: number
      tokens: number
      cost_usd: number
      cost_usd_minor: number
      pricing_status: string
      estimated: boolean
      unknown_pricing: boolean
    }>
  }
  by_plan: AdminAiCostRollupRow[]
  by_user: AdminAiCostRollupRow[]
  by_feature: AdminAiCostRollupRow[]
  by_persona: AdminAiCostRollupRow[]
  by_day: Array<{
    date: string
    runs: number
    tokens: number
    cost_usd: number
    cost_usd_minor: number
    revenue_inr: number
    gross_margin_inr: number
  }>
  daily: {
    by_plan: AdminAiCostDailyRow[]
    by_user: AdminAiCostDailyRow[]
    by_feature: AdminAiCostDailyRow[]
    by_persona: AdminAiCostDailyRow[]
    by_model: AdminAiCostDailyRow[]
  }
  top_users: AdminAiCostRollupRow[]
  margin_by_plan: Array<{
    plan: string
    revenue_inr: number
    ai_cost_inr: number
    ai_cost_usd: number
    gross_margin_inr: number
    gross_margin_inr_minor: number
    estimated: boolean
  }>
  caps: {
    currency: string
    minor_unit: string
    window: {
      day: string
      day_start: string
      day_resets_at: string
      month: string
      month_start: string
      month_resets_at: string
    }
    estimated_job_cost_usd: number
    enforcement: {
      mode: string
      in_flight_jobs_unaffected: boolean
      auto_suspend: boolean
      requires_actor_and_reason_log: boolean
    }
    global: {
      month_to_date_usd: number
      today_usd: number
      monthly_soft_cap_usd: number | null
      monthly_hard_cap_usd: number | null
      decision: string
      reasons: string[]
    }
    users: Array<{
      user_id: string
      plan: string
      month_to_date_usd: number
      today_usd: number
      monthly_soft_cap_usd: number | null
      monthly_hard_cap_usd: number | null
      daily_soft_cap_usd: number | null
      daily_hard_cap_usd: number | null
      decision: string
      reasons: string[]
      unknown_pricing_runs: number
      pricing_complete: boolean
    }>
    summary: {
      users_over_hard_cap: number
      users_over_soft_cap: number
      users_with_unknown_pricing: number
    }
  }
  outliers: Array<{
    dimension: string
    key: string
    user_id: string | null
    today_usd: number
    baseline_median_usd: number
    baseline_mad_usd: number
    threshold_usd: number
    multiple_of_median: number | null
    baseline_days: number
    active_baseline_days: number
    method: string
  }>
  alerts: Array<{
    severity: string
    code: string
    message: string
    value: number
    threshold: number
    user_id?: string
    date?: string
    dimension?: string
    reason?: string
  }>
  reconciliation: AdminAiCostReconciliation
  invoice_reconciliation: AdminAiCostReconciliation
}

export interface AdminAiCostReconciliation {
  contract_version: string
  status: string
  estimated: boolean
  provider_keys_required: boolean
  provider_key_included: boolean
  ledger_currency: string
  ledger_minor_unit: string
  ledger_total_usd: number
  ledger_total_minor: number
  tolerance_minor: number
  tolerance_usd: number
  sampled_invoice: {
    provided: boolean
    currency: string
    minor_unit: string
    total_minor: number | null
    reference: string | null
    variance_minor: number | null
    variance_usd?: number
    variance_percent: number | null
    within_tolerance: boolean | null
    status: string
  }
  sources: Array<{
    source: string
    runs: number
    tokens: number
    cost_usd: number
    cost_usd_minor: number
    estimated_runs: number
    unknown_pricing_runs: number
  }>
  contract: {
    required_fields: string[]
    supported_currencies: string[]
    minor_unit: string
    provider_credentials_required: boolean
    query_parameter: string
    note: string
  }
  notes: string[]
}

export interface AdminAiCostRollupRow {
  label: string
  plan?: string
  user_id?: string
  feature?: string
  persona?: string
  runs: number
  tokens: number
  cost_usd: number
  cost_usd_minor: number
  ai_cost_inr: number
  revenue_inr: number
  gross_margin_inr: number
  estimated: boolean
  estimated_runs: number
  unknown_pricing_runs: number
  revenue_attribution?: string
}

export interface AdminAiCostDailyRow extends AdminAiCostRollupRow {
  date: string
}

export interface AdminAiUsageMetrics {
  runs: number
  users: number
  successes: number
  errors: number
  pending: number
  success_rate: number
  error_rate: number
  tokens: number
  latency_p50_ms: number | null
  latency_p95_ms: number | null
  latency_avg_ms: number | null
  latency_samples: number
  credential_sources: Record<string, number>
}

export interface AdminAiUsageRow extends AdminAiUsageMetrics {
  label: string
  feature?: string
  provider?: string
  model?: string
  persona?: string
  plan?: string
  credential_source?: string
}

export interface AdminAiUsageResponse {
  period_days: number
  start_date: string
  end_date: string
  generated_at: string
  filters: {
    plan: string | null
    feature: string | null
    provider: string | null
    model: string | null
    persona: string | null
  }
  minimum_group_size: number
  suppressed_groups: number
  suppression: {
    minimum_group_size: number
    rule: string
    suppressed_groups: number
    by_dimension: Record<string, number>
  }
  totals: AdminAiUsageMetrics
  by_feature: AdminAiUsageRow[]
  by_provider: AdminAiUsageRow[]
  by_model: AdminAiUsageRow[]
  by_persona: AdminAiUsageRow[]
  by_plan: AdminAiUsageRow[]
  by_credential_source: AdminAiUsageRow[]
  reconciliation: {
    sources: Array<AdminAiUsageMetrics & { source: string; table: string }>
    total_events: number
    total_successes: number
    total_errors: number
    total_tokens: number
    resume_engine_runs: {
      source: string
      runs: number
      by_status: Record<string, number>
      successes: number
      partial: number
      errors: number
      pending: number
      latency_p50_ms: number | null
      latency_p95_ms: number | null
      latency_avg_ms: number | null
      latency_samples: number
      filters_applied: Record<string, string | null>
      note: string
    }
  }
  persona_source: string
  credential_source_note: string
  privacy: {
    aggregate_only: boolean
    per_user_rows: boolean
    content_fields_read: string[]
    content_fields_excluded: string[]
  }
  notes: string[]
}

export type AdminTimeseriesMetric =
  | 'events'
  | 'compilations'
  | 'optimizations'
  | 'revenue'
  | 'new_users'
  | 'active_users'

export type AdminTimeseriesDimension = 'plan' | 'provider' | 'feature' | 'signup_cohort'

export interface AdminFilteredTimeseriesResponse {
  metric: AdminTimeseriesMetric
  dimension: AdminTimeseriesDimension | null
  value: string | null
  days?: number
  start_date?: string
  end_date?: string
  points: Array<{ date: string; value: number }>
  breakdown: Array<{ label: string; value: number; users?: number }>
  total: number
  suppressed?: boolean
  suppressed_groups?: number
  minimum_group_size?: number
  filters?: {
    days: number
    metric: AdminTimeseriesMetric
    dimension: AdminTimeseriesDimension | null
    value: string | null
    start_date: string
    end_date: string
    timezone: string
  }
  generated_at: string
}

export interface AdminFeatureFrequencyBucket {
  key: string
  label: string
  users: number
  share: number
}

export interface AdminFeatureDepthRow {
  feature: string
  users: number
  events: number
  events_per_user: number
  median_events_per_user: number | null
  p95_events_per_user: number | null
  repeat_users: number
  repeat_rate: number
  habitual_users: number
  habitual_rate: number
  buckets: AdminFeatureFrequencyBucket[]
  breadth: {
    average_features_per_user: number
    median_features_per_user: number | null
    sole_feature_users: number
    multi_feature_users: number
  }
}

export interface AdminFeatureDepthBreadthSummary {
  average_features_per_user: number
  median_features_per_user: number | null
  distribution: Array<{ key: string; label: string; users: number }>
}

export interface AdminFeatureDepthResponse {
  days: number
  start_date: string
  end_date: string
  timezone: string
  filters: {
    days: number
    plan: string | null
    cohort: string | null
    start_date: string
    end_date: string
    timezone: string
  }
  minimum_group_size: number
  habitual_weekly_threshold: number
  habitual_minimum_events: number
  habitual_definition: string
  suppressed: boolean
  suppressed_features: number
  truncated_features: number
  totals: {
    users: number
    events: number
    features: number
    median_events_per_user: number | null
    p95_events_per_user: number | null
    repeat_users: number
    repeat_rate: number
    habitual_users: number
    habitual_rate: number
    breadth: AdminFeatureDepthBreadthSummary
  }
  features: AdminFeatureDepthRow[]
  generated_at: string
}

export type AdminFeatureAdoptionDimension = 'plan' | 'role' | 'cohort'

export interface AdminFeatureAdoptionRow {
  feature: string
  key: string
  label: string
  category: string
  description: string | null
  used_at_least_once: number
  weekly_active: number
  penetration: number
  weekly_active_penetration: number
  events: number
  last_used_at: string | null
}

export interface AdminFeatureAdoptionSegment {
  dimension: AdminFeatureAdoptionDimension
  key: string
  label: string
  denominator: number
  suppressed: boolean
  features: AdminFeatureAdoptionRow[]
}

export interface AdminFeatureAdoptionResponse {
  days: number
  start_date: string
  end_date: string
  timezone: string
  date_range: {
    start: string
    end: string
    days: number
    timezone: string
  }
  filters: {
    days: number
    start_date: string
    end_date: string
    plan: string[] | null
    role: string[] | null
    cohort: string[] | null
    feature: string | null
    timezone: string
  }
  minimum_segment_size: number
  feature_count: number
  visible_feature_count: number
  suppressed: boolean
  suppressed_segments: Record<AdminFeatureAdoptionDimension, number>
  segments: AdminFeatureAdoptionSegment[]
  reconciliation: {
    source: string
    audience_users: number
    usage_events: number
    matrix_events: number
    unmatched_events: number
    features_with_usage: number
    matched_rate: number
  }
  definitions: Record<string, string>
  generated_at: string
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
    if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
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

  async submitJob(req: JobSubmitRequest, accountContext?: AccountPreferenceRequestContext): Promise<JobSubmitResponse> {
    const response = await this.request<JobSubmitResponse>('/jobs/submit', {
      method: 'POST',
      body: JSON.stringify(req),
    }, accountContext)
    if (typeof window !== 'undefined') {
      trackBusinessEvent('job_submit', '/jobs/submit', { jobType: req.job_type })
    }
    return response
  }

  // ---------------------------------------------------------------- //
  //  Job state & result                                               //
  // ---------------------------------------------------------------- //

  async getJobState(jobId: string, fingerprint?: string): Promise<JobStateResponse> {
    return this.request<JobStateResponse>(`/jobs/${encodeURIComponent(jobId)}/state`, { headers: fingerprint ? { 'X-Device-Fingerprint': fingerprint } : undefined })
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

  async getLatestAcceptedArtifact(resumeId: string, accountContext: AccountPreferenceRequestContext, signal?: AbortSignal) {
    return fetchAcceptedArtifact(
      (requestSignal) => this.authedFetch(
        `${API_BASE}/resumes/${encodeURIComponent(resumeId)}/latest-accepted-artifact`,
        { cache: 'no-store', signal: requestSignal },
        accountContext,
      ),
      async (response) => {
        if (!response.ok) {
          const bodyText = await response.text().catch(() => '')
          throw new Error(`HTTP ${response.status}: ${parseApiErrorMessage(bodyText, response.statusText)}`)
        }
        return response.json() as Promise<{
          artifact: (import('@/lib/event-types').RenderArtifact & { job_id: string }) | null
          source_sha256: string
          content_revision: number
        }>
      },
      signal,
    )
  }

  async createResume(resume: ResumeCreate): Promise<ResumeResponse> {
    return this.request<ResumeResponse>('/resumes/', {
      method: 'POST',
      body: JSON.stringify(resume),
    })
  }

  async getBuilderCapabilities(): Promise<BuilderCapabilitiesResponse> {
    return this.request<BuilderCapabilitiesResponse>('/resumes/builder/capabilities', { cache: 'no-store' })
  }

  async getBuilderTemplates(): Promise<BuilderTemplateResponse[]> {
    return this.request<BuilderTemplateResponse[]>('/resumes/builder/templates')
  }

  async seedBuilderFromUpload(file: File): Promise<BuilderSeedUploadResponse> {
    const form = new FormData()
    form.append('file', file)
    const res = await this.authedFetch(`${API_BASE}/resumes/builder/v1/seed-upload`, {
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
    return this.request<BuilderResumeResponse>('/resumes/builder/v1', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async getBuilderResume(resumeId: string): Promise<BuilderResumeResponse> {
    return this.request<BuilderResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/builder/v1`)
  }

  async updateBuilderResume(
    resumeId: string,
    body: {
      title?: string
      template_id?: string
      structured_content?: StructuredResume
      force_reattach?: boolean
      expected_structured_version?: number
      expected_latex_content?: string
    }
  ): Promise<BuilderResumeResponse> {
    return this.request<BuilderResumeResponse>(`/resumes/${encodeURIComponent(resumeId)}/builder/v1`, {
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
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<SuggestionDecisionResponse> {
    return this.request<SuggestionDecisionResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/suggestion-decisions`,
      {
        method: 'POST',
        body: JSON.stringify(decision),
      },
      accountContext,
    )
  }

  /** Confirm a peer's Y.Map decision against the server before changing UI state. */
  async getSuggestionDecision(
    resumeId: string,
    suggestionId: string,
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<SuggestionDecisionResponse> {
    return this.request<SuggestionDecisionResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/suggestion-decisions/${encodeURIComponent(suggestionId)}`,
      {}, accountContext,
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

  async getAdminAnalyticsOverview(days: number = 30): Promise<AdminAnalyticsOverviewResponse> {
    return this.request<AdminAnalyticsOverviewResponse>(`/analytics/admin/overview?days=${days}`)
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

  async downloadArtifactPdf(
    jobId: string,
    artifactId: string,
    fingerprint?: string,
    signal?: AbortSignal,
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<Blob> {
    const url = `${API_BASE}/download/${encodeURIComponent(jobId)}/preview/${encodeURIComponent(artifactId)}`
    const headers = fingerprint ? { 'X-Device-Fingerprint': fingerprint } : undefined
    for (let attempt = 0; ; attempt += 1) {
      const res = await this.authedFetch(url, { signal, headers }, accountContext)
      if (res.ok) return res.blob()
      if (res.status !== 429 || attempt >= 2) throw new Error(`PDF preview failed: HTTP ${res.status}`)

      // A rate-limited artifact read is safe to retry: it is a GET for the same
      // immutable, owner-scoped artifact. Bound the wait so a stale preview
      // cannot hold the editor indefinitely, and stop immediately on identity
      // change/unmount via the caller's abort signal.
      const retryAfter = res.headers.get('Retry-After')
      const numericRetryAfter = retryAfter == null ? NaN : Number(retryAfter)
      const requestedDelay = Number.isFinite(numericRetryAfter)
        ? numericRetryAfter * 1000
        : retryAfter ? Date.parse(retryAfter) - Date.now() : NaN
      const delay = Number.isFinite(requestedDelay) && requestedDelay >= 0
        ? requestedDelay
        : 250 * (attempt + 1)
      if (delay > 3000) throw new Error('PDF preview failed: HTTP 429')
      await new Promise<void>((resolve, reject) => {
        if (signal?.aborted) { reject(new DOMException('Aborted', 'AbortError')); return }
        let timer: ReturnType<typeof setTimeout>
        const onAbort = () => {
          clearTimeout(timer)
          signal?.removeEventListener('abort', onAbort)
          reject(new DOMException('Aborted', 'AbortError'))
        }
        timer = setTimeout(() => {
          signal?.removeEventListener('abort', onAbort)
          resolve()
        }, delay)
        signal?.addEventListener('abort', onAbort, { once: true })
      })
    }
  }

  async getArtifactManifest(jobId: string, fingerprint?: string, signal?: AbortSignal) {
    return this.request<import('@/lib/event-types').RenderArtifact | null>(`/download/${encodeURIComponent(jobId)}/preview/manifest`, {
      signal, headers: fingerprint ? { 'X-Device-Fingerprint': fingerprint } : undefined,
    })
  }

  async getArtifactGeometry(jobId: string, artifactId: string, fingerprint?: string, signal?: AbortSignal) {
    return this.request<import('@/lib/resume-engine-types').ArtifactGeometry>(`/download/${encodeURIComponent(jobId)}/preview/${encodeURIComponent(artifactId)}/geometry`, {
      signal, headers: fingerprint ? { 'X-Device-Fingerprint': fingerprint } : undefined,
    })
  }

  async getEngineCapability(signal?: AbortSignal) {
    const response = await this.authedFetch(`${API_BASE}/public/engine/capabilities`, { signal, cache: 'no-store' })
    return readEngineCapability(response)
  }

  async getEngineProviders(accountContext: AccountPreferenceRequestContext, signal?: AbortSignal) {
    return this.request<import('@/lib/resume-engine-types').EngineProviderOptions>('/resumes/engine/providers', { signal }, accountContext)
  }

  async optimizeEngineDocument(resumeId: string, body: {
    expected_content_revision: number; expected_source_sha256: string; job_description: string
    effort: import('@/lib/resume-engine-types').OptimizationEffort
    provider?: import('@/lib/resume-engine-types').EngineProvider
    provider_model?: string
  }, accountContext?: AccountPreferenceRequestContext) {
    return this.request<JobSubmitResponse>(`/resumes/${encodeURIComponent(resumeId)}/engine/optimize`, {
      method: 'POST', body: JSON.stringify(body),
    }, accountContext)
  }

  async getEngineRun(resumeId: string, runId: string) {
    return this.request<import('@/lib/resume-engine-types').SemanticOptimizationRun>(`/resumes/${encodeURIComponent(resumeId)}/engine/runs/${encodeURIComponent(runId)}`)
  }

  async decideEngineRun(resumeId: string, runId: string, body: {
    accept_patch_ids: string[]; reject_patch_ids: string[]; expected_content_revision: number; expected_source_sha256: string
  }, accountContext?: AccountPreferenceRequestContext) {
    return this.request<{ latex_content: string; document: import('@/lib/resume-engine-types').ResumeEngineDocument;
      decisions: import('@/lib/resume-engine-types').OptimizationDecisions }>(`/resumes/${encodeURIComponent(resumeId)}/engine/runs/${encodeURIComponent(runId)}/decisions`, {
      method: 'POST', body: JSON.stringify(body),
    }, accountContext)
  }

  async getGuestEngineDocument(latex_content: string) {
    return this.request<{ document: import('@/lib/resume-engine-types').ResumeEngineDocument; latex_content: string }>('/public/engine/document', {
      method: 'POST', body: JSON.stringify({ latex_content }),
    })
  }

  async patchGuestEngineDocument(body: {
    latex_content: string; expected_source_sha256: string
    patches: Array<{ node_id: string; expected_node_revision: string; text: string }>
  }) {
    return this.request<{ document: import('@/lib/resume-engine-types').ResumeEngineDocument; latex_content: string }>('/public/engine/document/patch', {
      method: 'POST', body: JSON.stringify(body),
    })
  }

  async getEngineDocument(resumeId: string) {
    return this.request<{ document: import('@/lib/resume-engine-types').ResumeEngineDocument; latex_content: string }>(`/resumes/${encodeURIComponent(resumeId)}/engine/document`)
  }

  async uploadPdfImport(file: File, accountContext: AccountPreferenceRequestContext, signal?: AbortSignal) {
    const body = new FormData()
    body.append('file', file)
    return this.request<import('@/lib/pdf-import-types').PdfImportReceipt>('/resumes/imports/pdf', {
      method: 'POST', body, signal,
    }, accountContext)
  }

  async getPdfImport(importId: string, accountContext: AccountPreferenceRequestContext, signal?: AbortSignal) {
    return this.request<import('@/lib/pdf-import-types').PdfImportReceipt>(`/resumes/imports/${encodeURIComponent(importId)}`, { signal }, accountContext)
  }

  async getResumePdfImport(resumeId: string, accountContext: AccountPreferenceRequestContext, signal?: AbortSignal) {
    return this.request<import('@/lib/pdf-import-types').PdfImportReceipt>(`/resumes/${encodeURIComponent(resumeId)}/engine/import`, { signal }, accountContext)
  }

  async downloadPdfImportOriginal(importId: string, accountContext: AccountPreferenceRequestContext, signal?: AbortSignal): Promise<Blob> {
    const response = await this.authedFetch(`${API_BASE}/resumes/imports/${encodeURIComponent(importId)}/original`, { signal }, accountContext)
    if (!response.ok) throw new Error(`Original PDF could not be loaded (HTTP ${response.status})`)
    const declared = Number(response.headers.get('Content-Length'))
    if (Number.isFinite(declared) && declared > 10 * 1024 * 1024) throw new Error('Original PDF exceeds the import size limit')
    const blob = await response.blob()
    if (blob.size > 10 * 1024 * 1024 || !blob.size) throw new Error('Original PDF has an invalid size')
    return blob
  }

  async adaptPdfImport(importId: string, body: {
    template_id: string; title: string; expected_original_sha256: string
    field_edits?: Array<{ node_id: string; expected_node_revision: string; text: string }>
  }, accountContext: AccountPreferenceRequestContext, signal?: AbortSignal) {
    return this.request<import('@/lib/pdf-import-types').PdfImportAdaptation>(`/resumes/imports/${encodeURIComponent(importId)}/adapt`, {
      method: 'POST', body: JSON.stringify(body), signal,
    }, accountContext)
  }

  async patchEngineDocument(resumeId: string, body: {
    expected_content_revision: number; expected_source_sha256: string; merge_disjoint: boolean
    patches: Array<{ node_id: string; expected_node_revision: string; text: string }>
  }, accountContext?: AccountPreferenceRequestContext) {
    return this.request<{ latex_content: string; document: import('@/lib/resume-engine-types').ResumeEngineDocument }>(`/resumes/${encodeURIComponent(resumeId)}/engine/document`, {
      method: 'PATCH', body: JSON.stringify(body),
    }, accountContext)
  }

  async reorderEngineDocument(resumeId: string, body: {
    expected_content_revision: number; expected_source_sha256: string; container_id: string; ordered_ids: string[]
  }, accountContext: AccountPreferenceRequestContext) {
    return this.request<{ latex_content: string; document: import('@/lib/resume-engine-types').ResumeEngineDocument }>(`/resumes/${encodeURIComponent(resumeId)}/engine/structure`, {
      method: 'POST', body: JSON.stringify(body),
    }, accountContext)
  }

  async downloadArtifactSynctex(jobId: string, artifactId: string, fingerprint?: string, signal?: AbortSignal): Promise<string | null> {
    const response = await this.authedFetch(`${API_BASE}/download/${encodeURIComponent(jobId)}/preview/${encodeURIComponent(artifactId)}/synctex`, {
      signal, headers: fingerprint ? { 'X-Device-Fingerprint': fingerprint } : undefined,
    })
    if (!response.ok) return null
    return response.text()
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
    /** Auto-compile typing previews render in draft mode; explicit builds stay full. */
    preview?: boolean
  }, accountContext?: AccountPreferenceRequestContext): Promise<JobSubmitResponse> {
    return this.submitJob({
      job_type: 'latex_compilation',
      latex_content: body.latex_content,
      device_fingerprint: body.device_fingerprint,
      user_plan: body.user_plan,
      metadata: body.preview ? { ...(body.resume_id ? { resume_id: body.resume_id } : {}), preview: true }
        : body.resume_id ? { resume_id: body.resume_id } : undefined,
      compiler: body.compiler,
    }, accountContext)
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
    optId: string,
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<{ success: boolean; latex_content: string }> {
    return this.request(
      `/resumes/${encodeURIComponent(resumeId)}/restore-optimization/${encodeURIComponent(optId)}`,
      { method: 'POST' },
      accountContext,
    )
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

  async getCurrentSubscription(accountContext?: AccountPreferenceRequestContext): Promise<{
    success: boolean
    data?: CurrentSubscriptionResponse
    error?: string
  }> {
    try {
      const data = await this.request<CurrentSubscriptionResponse>('/subscription/current', {}, accountContext)
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  private async requireDodoBillingBackend(accountContext?: AccountPreferenceRequestContext): Promise<void> {
    // The frontend can deploy before the API rollout. Never dispatch a billing
    // mutation to an older backend merely because its billing is available.
    const capabilities = await this.request<{ billing?: { provider?: string } }>(
      '/subscription/plans', { cache: 'no-store' }, accountContext,
    )
    if (capabilities.billing?.provider !== 'dodo') {
      throw new Error('Dodo billing is not available on this server yet. Please try again after the update.')
    }
  }

  async reconcileSubscription(accountContext?: AccountPreferenceRequestContext): Promise<{
    success: boolean
    data?: SubscriptionReconciliationResponse
    error?: string
  }> {
    try {
      await this.requireDodoBillingBackend(accountContext)
      const data = await this.request<SubscriptionReconciliationResponse>(
        '/billing/dodo/subscription/reconcile',
        { method: 'POST' },
        accountContext,
      )
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async getAdminPlanCatalog(): Promise<AdminPlanCatalogResponse> {
    return this.request<AdminPlanCatalogResponse>('/admin/plan-catalog')
  }

  async updateAdminPlanQuota(sku: string, dimension: string, update: CatalogQuotaUpdate): Promise<AdminPlanCatalogResponse> {
    return this.request<AdminPlanCatalogResponse>(`/admin/plan-catalog/${encodeURIComponent(sku)}/quotas/${encodeURIComponent(dimension)}`, {
      method: 'PATCH',
      body: JSON.stringify(update),
    })
  }

  async updateAdminPlanCatalog(sku: string, update: CatalogPlanUpdate): Promise<AdminPlanCatalogResponse> {
    return this.request<AdminPlanCatalogResponse>(`/admin/plan-catalog/${encodeURIComponent(sku)}`, {
      method: 'PATCH',
      body: JSON.stringify(update),
    })
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
          provider?: string
          feature_enabled: boolean
          mode: 'enabled' | 'disabled' | 'unconfigured'
          available: boolean
          reason?: string | null
          message: string
        }
      }>('/subscription/plans', { cache: 'no-store' })
      const dodoCompatible = data.billing.provider === 'dodo'
      return {
        success: true,
        data: {
          plans: data.plans,
          billing: {
            provider: dodoCompatible ? 'dodo' : null,
            featureEnabled: data.billing.feature_enabled,
            mode: data.billing.mode,
            available: dodoCompatible && data.billing.available,
            reason: dodoCompatible ? data.billing.reason ?? null : 'billing_backend_update_required',
            message: dodoCompatible ? data.billing.message : 'Dodo billing is not available on this server yet. Please try again after the update.',
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
    },
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<{
    success: boolean
    data?: SubscriptionCreateResponse
    error?: string
  }> {
    try {
      await this.requireDodoBillingBackend(accountContext)
      const data = await this.request<SubscriptionCreateResponse>(
        '/billing/dodo/subscription/create',
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
        },
        accountContext,
      )
      captureAnalyticsEvent('checkout_started', {
        plan_key: planId,
        billing_period: options?.billingPeriod ?? 'monthly',
        has_coupon: Boolean(options?.couponCode),
        surface: 'billing',
      })
      return { success: true, data }
    } catch (e) {
      captureAnalyticsEvent('checkout_failed', {
        plan_key: planId,
        billing_period: options?.billingPeriod ?? 'monthly',
        surface: 'billing',
      })
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async cancelSubscription(accountContext?: AccountPreferenceRequestContext): Promise<{
    success: boolean
    message?: string
    error?: string
  }> {
    try {
      await this.requireDodoBillingBackend(accountContext)
      const data = await this.request<{ success: boolean; message?: string; error?: string }>(
        '/billing/dodo/subscription/cancel',
        { method: 'POST' },
        accountContext,
      )
      if (data.success) {
        captureAnalyticsEvent('subscription_cancel_requested', { surface: 'billing' })
      }
      return data
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async validateCoupon(
    code: string,
    planId: string,
    billingPeriod: 'monthly' | 'annual' = 'monthly',
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<{
    success: boolean
    data?: CouponValidationResponse
    error?: string
  }> {
    try {
      const data = await this.request<CouponValidationResponse>('/billing/validate-coupon', {
        method: 'POST',
        body: JSON.stringify({ code, planId, billingPeriod }),
      }, accountContext)
      return { success: true, data }
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async verifyStudentSubscription(token: string, accountContext?: AccountPreferenceRequestContext): Promise<{
    success: boolean
    data?: { success: boolean; message: string; shortUrl?: string }
    error?: string
  }> {
    try {
      await this.requireDodoBillingBackend(accountContext)
      const data = await this.request<{
        success: boolean
        message: string
        short_url?: string
      }>(`/billing/dodo/subscription/student/verify/${encodeURIComponent(token)}`, {}, accountContext)
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
    signal?: AbortSignal,
  ): Promise<QuickScoreResponse> {
    return this.request<QuickScoreResponse>('/ats/quick-score', {
      method: 'POST',
      signal,
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
  async exportResume(resumeId: string, format: string, guidedBuilder = false): Promise<Blob> {
    const prefix = guidedBuilder ? '/export/builder/v1' : '/export'
    const response = await this.authedFetch(`${this.baseUrl}${prefix}/${encodeURIComponent(resumeId)}/${encodeURIComponent(format)}`)
    if (!response.ok) {
      captureAnalyticsEvent('export_failed', { format, guided_builder: guidedBuilder, surface: 'export' })
      const bodyText = await response.text().catch(() => '')
      throw new Error(parseApiErrorMessage(bodyText, response.statusText, `Export failed (${response.status})`))
    }
    captureAnalyticsEvent('export_completed', { format, guided_builder: guidedBuilder, surface: 'export' })
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
    checkpointId: string,
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<CheckpointContentResponse> {
    return this.request<CheckpointContentResponse>(
      `/resumes/${encodeURIComponent(resumeId)}/checkpoints/${encodeURIComponent(checkpointId)}/content`,
      {},
      accountContext,
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

  async useTemplate(id: string, title?: string, locale?: string, accountContext?: AccountPreferenceRequestContext): Promise<{ resume_id: string; title: string }> {
    return this.request<{ resume_id: string; title: string }>(
      `/templates/${encodeURIComponent(id)}/use`,
      { method: 'POST', body: JSON.stringify({ title: title || null, locale: locale || null }) },
      accountContext,
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
    const result = await this.request<GenerateCoverLetterResponse>('/cover-letters/generate', {
      method: 'POST',
      body: JSON.stringify(params),
    })
    captureAnalyticsEvent('cover_letter_generated', { surface: 'cover_letter' })
    return result
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
    captureAnalyticsEvent('product_event', {
      event_type: eventType,
      ...(metadata as Record<string, string | number | boolean | null | undefined> | undefined),
    })
    try {
      await this.request<{ message: string }>('/analytics/track', {
        method: 'POST',
        body: JSON.stringify({ event_type: eventType, metadata }),
      })
    } catch {
      // Non-critical — don't disrupt user flow
    }
  }

  /**
   * Anonymous signup-attempt counter. Only the allowlisted provider label is
   * sent; the backend never uses it to attribute an account. Account provider,
   * completion and verification always come from server-owned auth state.
   */
  async trackSignupStarted(provider?: SignupAuthProvider): Promise<void> {
    try {
      await this.request<{ recorded: string; provider: string }>('/analytics/signup/started', {
        method: 'POST',
        body: JSON.stringify(provider ? { provider } : {}),
      })
    } catch {
      // Analytics must never block sign-up.
    }
  }

  async trackOAuthFailure(
    provider: SignupAuthProvider,
    failureCode: SignupOAuthFailureCode = 'callback_failed',
  ): Promise<void> {
    try {
      await this.request<{ recorded: string; provider: string }>('/analytics/signup/oauth-failure', {
        method: 'POST',
        body: JSON.stringify({ provider, failure_code: failureCode }),
      })
    } catch {
      // Non-critical.
    }
  }

  /**
   * Idempotent server-side milestone sync. Returns null when analytics is
   * unavailable so callers can ignore failures without branching.
   */
  async recordSignupMilestones(): Promise<SignupMilestonesResponse | null> {
    // Playwright servers expose a build-time test flag. Synthetic suites assert
    // exact request ledgers, so keep this non-essential telemetry local to the
    // fixture instead of letting it reach the network. Production never sets
    // NEXT_PUBLIC_PLAYWRIGHT_TEST and always records the server-derived
    // milestones.
    if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') return null
    try {
      return await this.request<SignupMilestonesResponse>('/analytics/signup/milestones', {
        method: 'POST',
      })
    } catch {
      return null
    }
  }

  async trackCompilation(compilationId: string, compilationStatus: string, compilationTime?: number): Promise<void> {
    captureAnalyticsEvent('compilation_tracked', {
      status: compilationStatus,
      duration_ms: compilationTime,
      surface: 'compilation',
    })
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
    captureAnalyticsEvent('optimization_tracked', {
      provider,
      model,
      tokens_used: tokensUsed,
      surface: 'optimization',
    })
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
    captureAnalyticsEvent('feature_used', { feature, surface: 'product' })
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
    const result = await this.request<ShareLinkResponse>(
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
    captureAnalyticsEvent('share_link_created', {
      anonymous,
      review_comments: Boolean(reviewComments),
      surface: 'share',
    })
    return result
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

  async updateFeatureFlag(key: string, enabled: boolean, reason: string): Promise<{
    key: string
    enabled: boolean
    label: string
    description: string | null
    updated_at: string | null
  }> {
    return this.request(`/admin/feature-flags/${encodeURIComponent(key)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled, reason }),
    })
  }

  // ---------------------------------------------------------------- //
  //  Entitlements — Admin Control Plane                              //
  // ---------------------------------------------------------------- //

  /** Per-user effective feature map (auth optional; anonymous → free map). */
  async getEntitlements(signal?: AbortSignal): Promise<EntitlementsResponse> {
    return this.request<EntitlementsResponse>('/config/entitlements?include_quotas=false', { cache: 'no-store', signal })
  }

  /** Full admin entitlements state: registry, kill-switches, matrix, plan families. */
  async getAdminEntitlements(): Promise<AdminEntitlementsState> {
    return this.request<AdminEntitlementsState>('/admin/entitlements')
  }

  /** Toggle a feature's global kill-switch. Returns fresh state. */
  async updateKillSwitch(
    key: string,
    enabled: boolean,
    reason: string,
    expectedEnabled?: boolean,
  ): Promise<AdminEntitlementsState> {
    return this.request<AdminEntitlementsState>(
      `/admin/entitlements/kill-switch/${encodeURIComponent(key)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ enabled, reason, expected_enabled: expectedEnabled }),
      },
    )
  }

  /** Toggle a single feature × plan-family matrix cell. Returns fresh state. */
  async updateMatrixCell(
    planFamily: string,
    featureKey: string,
    enabled: boolean,
    reason: string,
    expectedEnabled?: boolean,
  ): Promise<AdminEntitlementsState> {
    return this.request<AdminEntitlementsState>('/admin/entitlements/matrix', {
      method: 'PATCH',
      body: JSON.stringify({
        plan_family: planFamily,
        feature_key: featureKey,
        enabled,
        reason,
        expected_enabled: expectedEnabled,
      }),
    })
  }

  /** Account roles restrict access independently of plans and document permissions. */
  async updateRoleCell(
    role: EntitlementRole,
    featureKey: string,
    enabled: boolean,
    reason: string,
    expectedEnabled?: boolean,
  ): Promise<AdminEntitlementsState> {
    return this.request<AdminEntitlementsState>('/admin/entitlements/roles', {
      method: 'PATCH',
      body: JSON.stringify({
        role,
        feature_key: featureKey,
        enabled,
        reason,
        expected_enabled: expectedEnabled,
      }),
    })
  }

  async getAdminUsers(params?: {
    q?: string
    id?: string
    limit?: number
    offset?: number
  }): Promise<AdminUsersResponse> {
    const qs = new URLSearchParams()
    if (params?.q) qs.set('q', params.q)
    if (params?.id) qs.set('id', params.id)
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

  async getAdminActivation(params?: {
    days?: number
    plan?: string
    provider?: string
    activation_window_days?: number
  }): Promise<AdminActivationResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.plan) qs.set('plan', params.plan)
    if (params?.provider) qs.set('provider', params.provider)
    if (params?.activation_window_days != null) {
      qs.set('activation_window_days', String(params.activation_window_days))
    }
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminActivationResponse>(`/admin/analytics/activation${suffix}`)
  }

  async getAdminRetention(weeks = 8, signupMonth?: string): Promise<AdminRetentionResponse> {
    const qs = new URLSearchParams({ weeks: String(weeks) })
    if (signupMonth) qs.set('signup_month', signupMonth)
    return this.request<AdminRetentionResponse>(`/admin/analytics/retention?${qs}`)
  }

  async getAdminTrafficSources(params?: {
    days?: number
    start_date?: string
    end_date?: string
  }): Promise<AdminTrafficSourcesResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.start_date) qs.set('start_date', params.start_date)
    if (params?.end_date) qs.set('end_date', params.end_date)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminTrafficSourcesResponse>(`/admin/analytics/traffic-sources${suffix}`)
  }

  async getAdminLandingConversion(days = 30): Promise<AdminLandingConversionResponse> {
    const qs = new URLSearchParams({ days: String(days) })
    return this.request<AdminLandingConversionResponse>(`/admin/analytics/landing-conversion?${qs}`)
  }

  async getAdminTrialAttribution(params?: {
    days?: number
    start_date?: string
    end_date?: string
  }): Promise<AdminTrialAttributionResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.start_date) qs.set('start_date', params.start_date)
    if (params?.end_date) qs.set('end_date', params.end_date)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminTrialAttributionResponse>(
      `/admin/analytics/trial-attribution${suffix}`,
    )
  }

  async getAdminAiCost(params?: {
    days?: number
    plan?: string
    feature?: string
    persona?: string
    invoice_total_minor?: number
    invoice_reference?: string
  }): Promise<AdminAiCostResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.plan) qs.set('plan', params.plan)
    if (params?.feature) qs.set('feature', params.feature)
    if (params?.persona) qs.set('persona', params.persona)
    if (params?.invoice_total_minor != null) qs.set('invoice_total_minor', String(params.invoice_total_minor))
    if (params?.invoice_reference) qs.set('invoice_reference', params.invoice_reference)
    return this.request<AdminAiCostResponse>(`/admin/analytics/ai-cost?${qs}`)
  }

  async getAdminAiUsage(params?: {
    days?: number
    plan?: string
    feature?: string
    provider?: string
    model?: string
    persona?: string
  }): Promise<AdminAiUsageResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.plan) qs.set('plan', params.plan)
    if (params?.feature) qs.set('feature', params.feature)
    if (params?.provider) qs.set('provider', params.provider)
    if (params?.model) qs.set('model', params.model)
    if (params?.persona) qs.set('persona', params.persona)
    return this.request<AdminAiUsageResponse>(`/admin/analytics/ai-usage?${qs}`)
  }

  async getAdminCompileLatency(params?: {
    days?: number
    plan?: string
    compiler?: string
    template?: string
  }): Promise<AdminCompileLatencyResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.plan) qs.set('plan', params.plan)
    if (params?.compiler) qs.set('compiler', params.compiler)
    if (params?.template) qs.set('template', params.template)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminCompileLatencyResponse>(`/admin/analytics/compile-latency${suffix}`)
  }

  async getAdminCompileErrors(params?: {
    days?: number
    plan?: string
    compiler?: string
    template?: string
    error_class?: AdminCompileErrorClassKey
  }): Promise<AdminCompileErrorsResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.plan) qs.set('plan', params.plan)
    if (params?.compiler) qs.set('compiler', params.compiler)
    if (params?.template) qs.set('template', params.template)
    if (params?.error_class) qs.set('error_class', params.error_class)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminCompileErrorsResponse>(`/admin/analytics/compile-errors${suffix}`)
  }

  async getAdminFilteredTimeseries(params: {
    days?: number
    metric: AdminTimeseriesMetric
    dimension?: AdminTimeseriesDimension
    value?: string
  }): Promise<AdminFilteredTimeseriesResponse> {
    const qs = new URLSearchParams({ metric: params.metric })
    if (params.days != null) qs.set('days', String(params.days))
    if (params.dimension) qs.set('dimension', params.dimension)
    if (params.value) qs.set('value', params.value)
    return this.request<AdminFilteredTimeseriesResponse>(`/admin/analytics/timeseries?${qs}`)
  }

  async getAdminFeatureDepth(params?: {
    days?: number
    plan?: string
    cohort?: string
  }): Promise<AdminFeatureDepthResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.plan) qs.set('plan', params.plan)
    if (params?.cohort) qs.set('cohort', params.cohort)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminFeatureDepthResponse>(`/admin/analytics/feature-depth${suffix}`)
  }

  async getAdminFeatureAdoption(params?: {
    days?: number
    start_date?: string
    end_date?: string
    plan?: string
    role?: string
    cohort?: string
    feature?: string
  }): Promise<AdminFeatureAdoptionResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.start_date) qs.set('start_date', params.start_date)
    if (params?.end_date) qs.set('end_date', params.end_date)
    if (params?.plan) qs.set('plan', params.plan)
    if (params?.role) qs.set('role', params.role)
    if (params?.cohort) qs.set('cohort', params.cohort)
    if (params?.feature) qs.set('feature', params.feature)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminFeatureAdoptionResponse>(`/admin/analytics/feature-adoption${suffix}`)
  }

  async getAdminAttention(): Promise<AdminAttentionResponse> {
    return this.request<AdminAttentionResponse>('/admin/operations/attention')
  }

  async getAdminAlerts(params?: {
    state?: 'active' | 'open' | 'acknowledged' | 'snoozed' | 'resolved'
    severity?: 'critical' | 'high' | 'medium' | 'low'
    owner?: string
    kind?: string
    limit?: number
    offset?: number
  }): Promise<AdminAlertList> {
    const qs = new URLSearchParams()
    if (params?.state) qs.set('state', params.state)
    if (params?.severity) qs.set('severity', params.severity)
    if (params?.owner) qs.set('owner', params.owner)
    if (params?.kind) qs.set('kind', params.kind)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.offset != null) qs.set('offset', String(params.offset))
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminAlertList>(`/admin/alerts${suffix}`)
  }

  async updateAdminAlert(
    id: string,
    body: { state: 'acknowledged' | 'snoozed'; reason: string; snooze_minutes?: number },
  ): Promise<AdminAlert> {
    return this.request<AdminAlert>(`/admin/alerts/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  }

  async getAdminOperationsHealth(): Promise<AdminOperationsHealthResponse> {
    return this.request<AdminOperationsHealthResponse>('/admin/operations/health')
  }

  async getAdminOperationsQueues(): Promise<AdminQueueMetricsResponse> {
    return this.request<AdminQueueMetricsResponse>('/admin/operations/queues')
  }

  async getAdminStuckJobs(params?: {
    min_age_minutes?: number
    limit?: number
    status?: string
    job_id?: string
  }): Promise<AdminStuckJobList> {
    const qs = new URLSearchParams()
    if (params?.min_age_minutes != null) qs.set('min_age_minutes', String(params.min_age_minutes))
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.status) qs.set('status', params.status)
    if (params?.job_id) qs.set('job_id', params.job_id)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminStuckJobList>(`/admin/operations/stuck-jobs${suffix}`)
  }

  async retryAdminStuckJob(
    id: string,
    body: { reason: string; confirm: true; idempotency_key?: string },
  ): Promise<AdminStuckJobActionResponse> {
    return this.request<AdminStuckJobActionResponse>(
      `/admin/operations/stuck-jobs/${encodeURIComponent(id)}/retry`,
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  async cancelAdminStuckJob(
    id: string,
    body: { reason: string; confirm: true; idempotency_key?: string },
  ): Promise<AdminStuckJobActionResponse> {
    return this.request<AdminStuckJobActionResponse>(
      `/admin/operations/stuck-jobs/${encodeURIComponent(id)}/cancel`,
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  async fenceAdminStuckJob(
    id: string,
    body: { reason: string; confirm: true; idempotency_key?: string },
  ): Promise<AdminStuckJobActionResponse> {
    return this.request<AdminStuckJobActionResponse>(
      `/admin/operations/stuck-jobs/${encodeURIComponent(id)}/fence`,
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  async getAdminBillingSummary(
    days = 30,
    params?: {
      start?: string
      end?: string
      granularity?: 'day' | 'month'
      currency?: string
    },
  ): Promise<AdminBillingSummary> {
    const qs = new URLSearchParams({ days: String(days) })
    if (params?.start) qs.set('start', params.start)
    if (params?.end) qs.set('end', params.end)
    if (params?.granularity) qs.set('granularity', params.granularity)
    if (params?.currency) qs.set('currency', params.currency)
    return this.request<AdminBillingSummary>(`/admin/billing/summary?${qs}`)
  }

  async getAdminCheckoutFunnel(days = 30): Promise<AdminCheckoutFunnel> {
    const qs = new URLSearchParams({ days: String(days) })
    return this.request<AdminCheckoutFunnel>(`/admin/billing/checkout-funnel?${qs}`)
  }

  async getAdminSubscriptionAnalytics(params?: {
    days?: number
    start?: string
    end?: string
    signup_month?: string
    signup_from?: string
    signup_to?: string
    plan?: string
  }): Promise<AdminSubscriptionAnalyticsResponse> {
    const qs = new URLSearchParams()
    if (params?.days != null) qs.set('days', String(params.days))
    if (params?.start) qs.set('start', params.start)
    if (params?.end) qs.set('end', params.end)
    if (params?.signup_month) qs.set('signup_month', params.signup_month)
    if (params?.signup_from) qs.set('signup_from', params.signup_from)
    if (params?.signup_to) qs.set('signup_to', params.signup_to)
    if (params?.plan) qs.set('plan', params.plan)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminSubscriptionAnalyticsResponse>(
      `/admin/subscriptions/analytics${suffix}`,
    )
  }

  async getAdminBillingWebhooks(params?: {
    status?: string
    event_type?: string
    acknowledged?: boolean
    received_after?: string
    received_before?: string
    dead_letter?: boolean
    q?: string
    limit?: number
    offset?: number
  }): Promise<AdminBillingWebhookList> {
    const qs = new URLSearchParams()
    if (params?.status) qs.set('status', params.status)
    if (params?.event_type) qs.set('event_type', params.event_type)
    if (params?.acknowledged != null) qs.set('acknowledged', String(params.acknowledged))
    if (params?.received_after) qs.set('received_after', params.received_after)
    if (params?.received_before) qs.set('received_before', params.received_before)
    if (params?.dead_letter != null) qs.set('dead_letter', String(params.dead_letter))
    if (params?.q) qs.set('q', params.q)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.offset != null) qs.set('offset', String(params.offset))
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminBillingWebhookList>(`/admin/billing/webhooks${suffix}`)
  }

  async replayAdminWebhook(id: string, reason: string, confirmed = true): Promise<{
    status: string
    replayed: boolean
    message: string
    event: AdminBillingWebhookMutation
  }> {
    return this.request<{
      status: string
      replayed: boolean
      message: string
      event: AdminBillingWebhookMutation
    }>(`/admin/billing/webhooks/${encodeURIComponent(id)}/replay`, {
      method: 'POST',
      body: JSON.stringify({ reason, confirm: confirmed }),
    })
  }

  async getAdminBillingReconciliation(params?: {
    received_after?: string
    received_before?: string
    limit?: number
    offset?: number
  }): Promise<AdminBillingReconciliationList> {
    const qs = new URLSearchParams()
    if (params?.received_after) qs.set('received_after', params.received_after)
    if (params?.received_before) qs.set('received_before', params.received_before)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.offset != null) qs.set('offset', String(params.offset))
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminBillingReconciliationList>(`/admin/billing/reconciliation${suffix}`)
  }

  async acknowledgeAdminReconciliation(id: string, reason: string): Promise<AdminBillingWebhookMutation> {
    return this.request<AdminBillingWebhookMutation>(
      `/admin/billing/reconciliation/${encodeURIComponent(id)}/acknowledge`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
  }

  async replayAdminReconciliation(id: string, reason: string, confirmed = true): Promise<{
    status: string
    replayed: boolean
    message: string
    event: AdminBillingWebhookMutation
  }> {
    return this.request<{
      status: string
      replayed: boolean
      message: string
      event: AdminBillingWebhookMutation
    }>(`/admin/billing/reconciliation/${encodeURIComponent(id)}/replay`, {
      method: 'POST',
      body: JSON.stringify({ reason, confirm: confirmed }),
    })
  }

  async acknowledgeAdminWebhook(id: string, note: string): Promise<AdminBillingWebhookMutation> {
    return this.request<AdminBillingWebhookMutation>(
      `/admin/billing/webhooks/${encodeURIComponent(id)}/acknowledge`,
      { method: 'POST', body: JSON.stringify({ note }) },
    )
  }

  async reconcileAdminWebhook(id: string, note?: string): Promise<{
    status: string
    message: string
    event: AdminBillingWebhookMutation
  }> {
    return this.request<{ status: string; message: string; event: AdminBillingWebhookMutation }>(
      `/admin/billing/webhooks/${encodeURIComponent(id)}/reconcile`, {
      method: 'POST',
      body: JSON.stringify({ note: note || undefined }),
    })
  }

  async getAdminRefundRequests(params?: {
    status?: string
    limit?: number
    offset?: number
  }): Promise<AdminRefundList> {
    const qs = new URLSearchParams()
    if (params?.status) qs.set('status', params.status)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.offset != null) qs.set('offset', String(params.offset))
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminRefundList>(`/admin/billing/refunds${suffix}`)
  }

  async createAdminRefundRequest(body: {
    payment_id: string
    amount?: number | null
    provider_item_id?: string | null
    tax_inclusive?: boolean
    reason: string
  }): Promise<AdminRefundRequest> {
    return this.request<AdminRefundRequest>('/admin/billing/refunds', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async decideAdminRefund(id: string, decision: 'approve' | 'reject', note: string): Promise<AdminRefundRequest> {
    return this.request<AdminRefundRequest>(
      `/admin/billing/refunds/${encodeURIComponent(id)}/${decision}`,
      { method: 'POST', body: JSON.stringify({ note }) },
    )
  }

  async executeAdminRefund(id: string, note?: string): Promise<AdminRefundRequest> {
    return this.request<AdminRefundRequest>(
      `/admin/billing/refunds/${encodeURIComponent(id)}/execute`,
      { method: 'POST', body: JSON.stringify({ note: note || undefined }) },
    )
  }

  async reconcileAdminRefund(id: string, note?: string): Promise<AdminRefundRequest> {
    return this.request<AdminRefundRequest>(
      `/admin/billing/refunds/${encodeURIComponent(id)}/reconcile`,
      { method: 'POST', body: JSON.stringify({ note: note || undefined }) },
    )
  }

  async getAdminUser360(id: string): Promise<AdminUser360> {
    return this.request<AdminUser360>(`/admin/users/${encodeURIComponent(id)}/360`)
  }

  async revealAdminUserPii(
    id: string,
    field: 'email' | 'name',
    reason: string,
  ): Promise<{ field: 'email' | 'name'; value: string | null }> {
    return this.request<{ field: 'email' | 'name'; value: string | null }>(
      `/admin/users/${encodeURIComponent(id)}/reveal-pii`,
      { method: 'POST', body: JSON.stringify({ field, reason }) },
    )
  }

  async changeAdminUserPlan(
    id: string,
    body: { plan: string; status: string; reason: string },
  ): Promise<{ subscription_plan: string; subscription_status: string }> {
    return this.request<{ subscription_plan: string; subscription_status: string }>(
      `/admin/users/${encodeURIComponent(id)}/plan`,
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  async resetAdminUserTrial(id: string, reason: string): Promise<{ trial_used: boolean; device_trials_reset: number }> {
    return this.request<{ trial_used: boolean; device_trials_reset: number }>(
      `/admin/users/${encodeURIComponent(id)}/trial/reset`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
  }

  async grantAdminUserFeature(
    id: string,
    body: { feature_key: string; reason: string },
  ): Promise<AdminUserActionEffective> {
    return this.request<AdminUserActionEffective>(
      `/admin/users/${encodeURIComponent(id)}/features/grant`,
      { method: 'POST', body: JSON.stringify({ ...body, confirm: true }) },
    )
  }

  async revokeAdminUserFeature(
    id: string,
    body: { feature_key: string; reason: string },
  ): Promise<AdminUserActionEffective> {
    return this.request<AdminUserActionEffective>(
      `/admin/users/${encodeURIComponent(id)}/features/revoke`,
      { method: 'POST', body: JSON.stringify({ ...body, confirm: true }) },
    )
  }

  async extendAdminUserTrial(
    id: string,
    body: { days: number; reason: string },
  ): Promise<AdminUserTrialActionResult> {
    return this.request<AdminUserTrialActionResult>(
      `/admin/users/${encodeURIComponent(id)}/trial/extend`,
      { method: 'POST', body: JSON.stringify({ ...body, confirm: true }) },
    )
  }

  async setAdminUserTrialEligibility(
    id: string,
    body: { eligible: boolean; reason: string },
  ): Promise<AdminUserTrialActionResult> {
    return this.request<AdminUserTrialActionResult>(
      `/admin/users/${encodeURIComponent(id)}/trial/eligibility`,
      { method: 'POST', body: JSON.stringify({ ...body, confirm: true }) },
    )
  }

  async resetAdminUserQuota(
    id: string,
    body: { reason: string; dimension?: 'compilations' | 'optimizations' | 'ai_assists' },
  ): Promise<{
    dimensions: string[]
    deleted_keys: number
    results: Array<{
      dimension: string
      window: 'day' | 'month'
      period: string
      limit: number | null
      before_used: number
      after_used: number
      deleted: number
    }>
    quota: AdminUserQuotaSnapshot
  }> {
    return this.request(
      `/admin/users/${encodeURIComponent(id)}/quota/reset`,
      { method: 'POST', body: JSON.stringify({ ...body, confirm: true }) },
    )
  }

  async revokeAdminUserSessions(id: string, reason: string): Promise<{ revoked_sessions: number }> {
    return this.request<{ revoked_sessions: number }>(
      `/admin/users/${encodeURIComponent(id)}/sessions/revoke`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
  }

  async revokeAdminUserPasskeys(id: string, reason: string): Promise<{ revoked_passkeys: number }> {
    return this.request<{ revoked_passkeys: number }>(
      `/admin/users/${encodeURIComponent(id)}/passkeys/revoke`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
  }

  async revokeAdminUserApiKeys(
    id: string,
    body: { reason: string; scope: 'byok' | 'developer' | 'all' },
  ): Promise<{ revoked_byok_keys: number; revoked_developer_keys: number }> {
    return this.request<{ revoked_byok_keys: number; revoked_developer_keys: number }>(
      `/admin/users/${encodeURIComponent(id)}/api-keys/revoke`,
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  async revokeAdminUserSession(
    id: string,
    sessionId: string,
    reason: string,
  ): Promise<AdminCredentialRevokeResponse> {
    return this.request<AdminCredentialRevokeResponse>(
      `/admin/users/${encodeURIComponent(id)}/sessions/${encodeURIComponent(sessionId)}/revoke`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
  }

  async revokeAdminUserPasskey(
    id: string,
    passkeyId: string,
    reason: string,
  ): Promise<AdminCredentialRevokeResponse> {
    return this.request<AdminCredentialRevokeResponse>(
      `/admin/users/${encodeURIComponent(id)}/passkeys/${encodeURIComponent(passkeyId)}/revoke`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
  }

  async revokeAdminUserByokKey(
    id: string,
    keyId: string,
    reason: string,
  ): Promise<AdminCredentialRevokeResponse> {
    return this.request<AdminCredentialRevokeResponse>(
      `/admin/users/${encodeURIComponent(id)}/byok-keys/${encodeURIComponent(keyId)}/revoke`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
  }

  async revokeAdminUserDeveloperKey(
    id: string,
    keyId: string,
    reason: string,
  ): Promise<AdminCredentialRevokeResponse> {
    return this.request<AdminCredentialRevokeResponse>(
      `/admin/users/${encodeURIComponent(id)}/developer-keys/${encodeURIComponent(keyId)}/revoke`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
  }

  async getAdminAudit(params?: {
    actor_user_id?: string
    action?: string
    target_type?: string
    target_id?: string
    created_after?: string
    created_before?: string
    limit?: number
    cursor?: string
  }): Promise<AdminAuditList> {
    const qs = new URLSearchParams()
    for (const key of ['actor_user_id', 'action', 'target_type', 'target_id', 'created_after', 'created_before'] as const) {
      const value = params?.[key]
      if (value) qs.set(key, value)
    }
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.cursor) qs.set('cursor', params.cursor)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminAuditList>(`/admin/audit${suffix}`)
  }

  /** Read-only history for feature flags, kill-switches and entitlement cells. */
  async getAdminChangeHistory(params?: {
    key?: string
    target_id?: string
    actor_user_id?: string
    action?: string
    created_after?: string
    created_before?: string
    limit?: number
    cursor?: string
  }): Promise<AdminChangeHistoryList> {
    const qs = new URLSearchParams()
    for (const key of ['key', 'target_id', 'actor_user_id', 'action', 'created_after', 'created_before'] as const) {
      const value = params?.[key]
      if (value) qs.set(key, value)
    }
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.cursor) qs.set('cursor', params.cursor)
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<AdminChangeHistoryList>(`/admin/change-history${suffix}`)
  }

  // ---------------------------------------------------------------- //
  //  GDPR data-subject workflow                                      //
  // ---------------------------------------------------------------- //

  async getGdprPolicy(): Promise<GdprPolicy> {
    return this.request<GdprPolicy>('/account/gdpr/policy')
  }

  async getGdprRequests(limit = 50): Promise<GdprRequestList> {
    const suffix = limit ? `?limit=${encodeURIComponent(String(limit))}` : ''
    return this.request<GdprRequestList>(`/account/gdpr/requests${suffix}`)
  }

  async getGdprRequest(id: string): Promise<GdprRequestSummary> {
    return this.request<GdprRequestSummary>(
      `/account/gdpr/requests/${encodeURIComponent(id)}`,
    )
  }

  async requestGdprExport(): Promise<GdprExportResponse> {
    return this.request<GdprExportResponse>('/account/gdpr/exports', {
      method: 'POST',
    })
  }

  async requestGdprDeletion(body: {
    confirmation: string
    reason?: string
  }): Promise<GdprDeletionResponse> {
    return this.request<GdprDeletionResponse>('/account/gdpr/deletion', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async cancelGdprDeletion(id: string): Promise<GdprRequestSummary> {
    return this.request<GdprRequestSummary>(
      `/account/gdpr/deletion/${encodeURIComponent(id)}/cancel`,
      { method: 'POST' },
    )
  }

  async downloadGdprExport(id: string, token: string): Promise<Blob> {
    const response = await this.authedFetch(
      `${API_BASE}/account/gdpr/exports/${encodeURIComponent(id)}/download`,
      { headers: { 'X-GDPR-Export-Token': token } },
    )
    if (!response.ok) {
      const bodyText = await response.text().catch(() => '')
      throw new Error(`HTTP ${response.status}: ${parseApiErrorMessage(bodyText, response.statusText)}`)
    }
    return response.blob()
  }

  async getAdminGdprRequests(params?: {
    status?: GdprRequestStatus
    request_type?: GdprRequestType
    limit?: number
    offset?: number
  }): Promise<GdprRequestList> {
    const qs = new URLSearchParams()
    if (params?.status) qs.set('status', params.status)
    if (params?.request_type) qs.set('request_type', params.request_type)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.offset != null) qs.set('offset', String(params.offset))
    const suffix = qs.toString() ? `?${qs}` : ''
    return this.request<GdprRequestList>(`/admin/gdpr/requests${suffix}`)
  }

  async reviewAdminGdprRequest(
    id: string,
    body: { decision: 'approved' | 'rejected'; note: string },
  ): Promise<GdprRequestSummary> {
    return this.request<GdprRequestSummary>(
      `/admin/gdpr/requests/${encodeURIComponent(id)}/review`,
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  async executeAdminGdprDeletion(
    id: string,
    note?: string,
  ): Promise<GdprRequestSummary> {
    return this.request<GdprRequestSummary>(
      `/admin/gdpr/requests/${encodeURIComponent(id)}/execute`,
      {
        method: 'POST',
        body: JSON.stringify({ note: note || null }),
      },
    )
  }

  async getAdminGdprLegalHolds(
    activeOnly = true,
  ): Promise<GdprLegalHoldList> {
    const suffix = activeOnly ? '?active_only=true' : '?active_only=false'
    return this.request<GdprLegalHoldList>(`/admin/gdpr/legal-holds${suffix}`)
  }

  async placeAdminGdprLegalHold(body: {
    user_id: string
    reason: string
  }): Promise<GdprLegalHold> {
    return this.request<GdprLegalHold>('/admin/gdpr/legal-holds', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async releaseAdminGdprLegalHold(
    id: string,
    reason: string,
  ): Promise<GdprLegalHold> {
    return this.request<GdprLegalHold>(
      `/admin/gdpr/legal-holds/${encodeURIComponent(id)}/release`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    )
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

  async generateInterviewPrep(body: GenerateInterviewPrepRequest, accountContext?: AccountPreferenceRequestContext): Promise<GenerateInterviewPrepApiResponse> {
    return this.request<GenerateInterviewPrepApiResponse>('/interview-prep/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }, accountContext)
  }

  async getInterviewPrep(prepId: string): Promise<InterviewPrepResponse> {
    return this.request<InterviewPrepResponse>(`/interview-prep/${encodeURIComponent(prepId)}`)
  }

  async listInterviewPrep(resumeId: string, accountContext?: AccountPreferenceRequestContext): Promise<InterviewPrepResponse[]> {
    return this.request<InterviewPrepResponse[]>(`/resumes/${encodeURIComponent(resumeId)}/interview-prep`, {}, accountContext)
  }

  async deleteInterviewPrep(prepId: string, accountContext?: AccountPreferenceRequestContext): Promise<void> {
    const res = await this.authedFetch(`${API_BASE}/interview-prep/${encodeURIComponent(prepId)}`, {
      method: 'DELETE',
    }, accountContext)
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '')
      throw new Error(`HTTP ${res.status}: ${parseApiErrorMessage(bodyText, res.statusText)}`)
    }
  }

  async evaluateInterviewSimulation(
    prepId: string,
    body: EvaluateInterviewSimulationRequest,
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<EvaluateInterviewSimulationResponse> {
    return this.request<EvaluateInterviewSimulationResponse>(
      `/interview-prep/${encodeURIComponent(prepId)}/simulate`,
      { method: 'POST', body: JSON.stringify(body) },
      accountContext,
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

  async getDropboxStatus(accountContext?: AccountPreferenceRequestContext): Promise<DropboxStatusResponse> {
    return this.request<DropboxStatusResponse>('/dropbox/status', {}, accountContext)
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

  async getZoteroStatus(accountContext?: AccountPreferenceRequestContext): Promise<ZoteroStatusResponse> {
    return this.request<ZoteroStatusResponse>('/zotero/status', {}, accountContext)
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

  async getMendeleyStatus(accountContext?: AccountPreferenceRequestContext): Promise<MendeleyStatusResponse> {
    return this.request<MendeleyStatusResponse>('/mendeley/status', {}, accountContext)
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
    const result = await this.request<GeneratePortfolioResponse>(
      `/resumes/${resumeId}/generate-portfolio`,
      { method: 'POST' }
    )
    captureAnalyticsEvent('portfolio_generated', { surface: 'portfolio' })
    return result
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
  }, accountContext?: AccountPreferenceRequestContext): Promise<TenantResponse> {
    return this.request<TenantResponse>('/tenants', {
      method: 'POST',
      body: JSON.stringify(body),
    }, accountContext)
  }

  async listMyTenants(accountContext?: AccountPreferenceRequestContext): Promise<TenantResponse[]> {
    return this.request<TenantResponse[]>('/tenants/my', {}, accountContext)
  }

  async updateTenant(
    tenantId: string,
    body: {
      name?: string
      logo_url?: string | null
      primary_color?: string | null
      custom_domain?: string | null
      active?: boolean
    },
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<TenantResponse> {
    return this.request<TenantResponse>(`/tenants/${tenantId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }, accountContext)
  }

  async listTenantMembers(tenantId: string, accountContext?: AccountPreferenceRequestContext): Promise<MemberResponse[]> {
    return this.request<MemberResponse[]>(`/tenants/${tenantId}/members`, {}, accountContext)
  }

  async inviteTenantMember(
    tenantId: string,
    email: string,
    role: 'admin' | 'member' = 'member',
    cohortId?: string,
    accountContext?: AccountPreferenceRequestContext,
  ): Promise<TenantInvitationResponse> {
    return this.request<TenantInvitationResponse>(`/tenants/${tenantId}/members/invite`, {
      method: 'POST',
      body: JSON.stringify({ email, role, cohort_id: cohortId }),
    }, accountContext)
  }

  async removeTenantMember(tenantId: string, userId: string, accountContext?: AccountPreferenceRequestContext): Promise<void> {
    await this.request<void>(`/tenants/${tenantId}/members/${userId}`, {
      method: 'DELETE',
    }, accountContext)
  }

  async acceptTenantInvitation(token: string): Promise<MemberResponse> {
    return this.request<MemberResponse>(`/tenants/invitations/${encodeURIComponent(token)}/accept`, {
      method: 'POST',
    })
  }

  async leaveTenant(tenantId: string): Promise<void> {
    await this.request<void>(`/tenants/${tenantId}/membership`, { method: 'DELETE' })
  }

  async createTenantCohort(tenantId: string, name: string, accountContext?: AccountPreferenceRequestContext): Promise<TenantCohort> {
    return this.request<TenantCohort>(`/tenants/${tenantId}/cohorts`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }, accountContext)
  }

  async listTenantCohorts(tenantId: string, accountContext?: AccountPreferenceRequestContext): Promise<TenantCohort[]> {
    return this.request<TenantCohort[]>(`/tenants/${tenantId}/cohorts`, {}, accountContext)
  }

  async listCohortSubmissions(tenantId: string, cohortId: string, accountContext?: AccountPreferenceRequestContext): Promise<CohortSubmission[]> {
    return this.request<CohortSubmission[]>(
      `/tenants/${tenantId}/cohorts/${cohortId}/submissions`, {}, accountContext,
    )
  }

  async getTenantStats(tenantId: string, accountContext?: AccountPreferenceRequestContext): Promise<TenantStats> {
    return this.request<TenantStats>(`/tenants/${tenantId}/stats`, {}, accountContext)
  }

  async verifyTenantDomain(tenantId: string, accountContext?: AccountPreferenceRequestContext): Promise<DomainVerifyResponse> {
    return this.request<DomainVerifyResponse>(`/tenants/${tenantId}/domain/verify`, {
      method: 'POST',
    }, accountContext)
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

  async exportCanva(resumeId: string, guidedBuilder = false): Promise<CanvaResumeExport> {
    const prefix = guidedBuilder ? '/export/builder/v1' : '/export'
    return this.request<CanvaResumeExport>(`${prefix}/${encodeURIComponent(resumeId)}/canva`)
  }

  async exportFigma(resumeId: string, guidedBuilder = false): Promise<FigmaResumeExport> {
    const prefix = guidedBuilder ? '/export/builder/v1' : '/export'
    return this.request<FigmaResumeExport>(`${prefix}/${encodeURIComponent(resumeId)}/figma`)
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
