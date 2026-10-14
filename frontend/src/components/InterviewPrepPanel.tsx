'use client'

import { useState, useEffect, useCallback, useRef, type MutableRefObject } from 'react'
import { ChevronDown, ChevronRight, Loader2, RefreshCw, Trash2, BrainCircuit, BookOpen, HelpCircle, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type InterviewPrepResponse, type InterviewQuestion } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'
import InterviewSimulation from '@/components/InterviewSimulation'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import { useAccountContentScope, type AccountContentScope } from '@/contexts/AccountContentScope'

// ─── Types ───────────────────────────────────────────────────────────────────

type QuestionCategory = 'behavioral' | 'technical' | 'motivational' | 'difficult'

const CATEGORIES: { key: QuestionCategory; label: string; icon: React.ElementType }[] = [
  { key: 'behavioral', label: 'Behavioral', icon: BrainCircuit },
  { key: 'technical', label: 'Technical', icon: Zap },
  { key: 'motivational', label: 'Motivational', icon: BookOpen },
  { key: 'difficult', label: 'Difficult', icon: HelpCircle },
]

// ─── Question Card ────────────────────────────────────────────────────────────

function QuestionCard({ q, index }: { q: InterviewQuestion; index: number }) {
  const [starExpanded, setStarExpanded] = useState(false)
  const [notes, setNotes] = useState('')

  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-3 space-y-2">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[10px] font-bold text-fg-3">
          {index + 1}
        </span>
        <p className="text-[12px] font-semibold leading-relaxed text-fg">{q.question}</p>
      </div>
      {q.what_interviewer_assesses && (
        <p className="ml-7 text-[11px] italic text-fg-3 leading-relaxed">
          {q.what_interviewer_assesses}
        </p>
      )}
      {(q.recommended_seconds || q.spoken_answer_tip) && (
        <div className="ml-7 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-fg-3">
          {q.recommended_seconds && (
            <span className="rounded bg-surface-2 px-1.5 py-0.5 font-medium">
              Aim for {q.recommended_seconds}s
            </span>
          )}
          {q.spoken_answer_tip && <span>{q.spoken_answer_tip}</span>}
        </div>
      )}
      {q.star_hint && (
        <div className="ml-7">
          <button
            onClick={() => setStarExpanded(v => !v)}
            className="flex items-center gap-1 text-[10px] font-medium text-accent-strong hover:text-accent-strong transition"
          >
            {starExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            STAR Hint
          </button>
          {starExpanded && (
            <div className="mt-1.5 rounded-[var(--radius-md)] border border-accent bg-accent-soft p-2.5 text-[11px] text-fg-2 leading-relaxed whitespace-pre-line">
              {q.star_hint.split(' | ').map((part, i) => (
                <p key={i} className={i > 0 ? 'mt-1' : ''}>
                  <span className="font-semibold text-accent-strong">{part.split(':')[0]}:</span>
                  {part.substring(part.indexOf(':') + 1)}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
      {q.ideal_response_outline && q.ideal_response_outline.length > 0 && (
        <div className="ml-7 rounded-[var(--radius-md)] border border-line bg-surface-2 p-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
            Strong-answer outline
          </p>
          <ul className="mt-1.5 space-y-1 text-[11px] leading-relaxed text-fg-2">
            {q.ideal_response_outline.map((point) => (
              <li key={point} className="flex gap-1.5">
                <span aria-hidden="true" className="text-fg-3">•</span>
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <textarea
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Add notes (session only)…"
        rows={1}
        className="ml-7 w-[calc(100%-1.75rem)] resize-none rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-1.5 text-[11px] text-fg-2 outline-none placeholder:text-fg-3 focus:border-line-2 transition"
      />
    </div>
  )
}

// ─── Main Panel ──────────────────────────────────────────────────────────────

export type InterviewPrepScope = {
  ownerId: string | null
  authToken: string | null
  resumeId: string
  generation: number
  ready: boolean
  authReady: boolean
  recoveryAvailable: boolean
  recoveryIdentity: object | null
}

interface InterviewPrepPanelProps {
  resumeId: string
  defaultJobDescription?: string
  ownerScopeRef: MutableRefObject<InterviewPrepScope>
  sourceReady: () => boolean
}

export default function InterviewPrepPanel(props: InterviewPrepPanelProps) {
  const accountScope = useAccountContentScope()
  const scope = props.ownerScopeRef.current
  if (!accountScope?.isCurrent() || scope.recoveryIdentity !== accountScope.recoveryIdentity
    || !scope.ownerId || scope.resumeId !== props.resumeId) return null
  // The parent renews the scope during render, before old effect cleanup.
  // Returning to the same account/document gets a fresh private subtree.
  return <InterviewPrepContent key={`${scope.ownerId}:${scope.resumeId}:${scope.generation}`}
    {...props} ownerScope={scope} accountScope={accountScope} />
}

function InterviewPrepContent({ resumeId, defaultJobDescription = '', ownerScopeRef, ownerScope, sourceReady, accountScope }: InterviewPrepPanelProps & { ownerScope: InterviewPrepScope; accountScope: AccountContentScope }) {
  const mountedRef = useRef(true)
  const authToken = ownerScope.authToken
  // Recovery outlives same-owner uncertainty. Admission is pinned to the exact
  // outer account/source leases, including snapshots this child never rendered.
  const isCurrentOwner = useCallback(() => mountedRef.current && accountScope.isCurrent()
    && accountScope.recoveryIdentity === ownerScope.recoveryIdentity && ownerScopeRef.current === ownerScope,
  [accountScope, ownerScope, ownerScopeRef])
  const canActForOwner = useCallback(() => isCurrentOwner() && accountScope.canAdmit()
    && Boolean(authToken) && ownerScope.authToken === authToken && ownerScope.ready && sourceReady(),
  [accountScope, authToken, isCurrentOwner, ownerScope, sourceReady])
  const canRecoverForOwner = useCallback(() => isCurrentOwner() && accountScope.canAdmit()
    && Boolean(authToken) && ownerScope.authToken === authToken && ownerScope.authReady,
  [accountScope, authToken, isCurrentOwner, ownerScope])
  const { can, loading: entitlementsLoading } = useEntitlements()
  const canRef = useRef(can)
  canRef.current = can
  const generatingRef = useRef(false)
  const deletingRef = useRef(new Set<string>())
  const [sessions, setSessions] = useState<InterviewPrepResponse[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  // A second admission must not displace the only watched generation.
  const activeJobIdRef = useRef<string | null>(null)
  const canGenerate = can('e02') && canActForOwner() && activeJobId === null
  const [jobDescription, setJobDescription] = useState(defaultJobDescription)
  const [companyName, setCompanyName] = useState('')
  const [roleTitleInput, setRoleTitleInput] = useState('')
  const [activeCategory, setActiveCategory] = useState<QuestionCategory>('behavioral')
  const loadGenerationRef = useRef(0)
  const readGenerationRef = useRef<number | null>(null)
  const completionRefreshPendingRef = useRef(false)
  const deletedPrepIdsRef = useRef(new Set<string>())
  const generationPlaceholdersRef = useRef(new Map<string, InterviewPrepResponse>())
  // Mutations can finish in the same React batch. Keep the owned collection and
  // selection authoritative synchronously so each completion sees the last one.
  const sessionsRef = useRef(sessions)
  const selectedSessionIdRef = useRef(selectedSessionId)
  const selectSession = (id: string | null) => {
    if (!isCurrentOwner()) return
    selectedSessionIdRef.current = id
    setSelectedSessionId(id)
  }

  const { state: jobStream } = useJobStream(activeJobId)

  const loadSessions = useCallback(async () => {
    if (!canRecoverForOwner()) return
    const generation = ++loadGenerationRef.current
    readGenerationRef.current = generation
    setIsLoading(true)
    setLoadError(null)
    try {
      const data = await apiClient.listInterviewPrep(resumeId, {
        authToken: authToken!,
        isCurrent: () => canRecoverForOwner() && generation === loadGenerationRef.current,
      })
      if (!isCurrentOwner() || generation !== loadGenerationRef.current) return
      // Even a replacement recovery read must not reverse admitted mutations.
      for (const session of data) generationPlaceholdersRef.current.delete(session.id)
      const recovered = [
        ...Array.from(generationPlaceholdersRef.current.values()).reverse(),
        ...data.filter(session => !deletedPrepIdsRef.current.has(session.id)),
      ]
      completionRefreshPendingRef.current = false
      sessionsRef.current = recovered
      setSessions(recovered)
      const selected = recovered.some(session => session.id === selectedSessionIdRef.current)
        ? selectedSessionIdRef.current : recovered[0]?.id ?? null
      selectedSessionIdRef.current = selected
      setSelectedSessionId(selected)
    } catch (error) {
      if (isCurrentOwner() && generation === loadGenerationRef.current) {
        // A request still waiting for auth may be rejected before dispatch.
        // Keep admitted completion recovery pending for the next valid lease.
        if (!canRecoverForOwner()) {
          sessionsLoadedRef.current = false
          return
        }
        completionRefreshPendingRef.current = false
        setLoadError(error instanceof Error ? error.message : 'Failed to load interview-prep sessions')
      }
    } finally {
      if (readGenerationRef.current === generation) readGenerationRef.current = null
      if (isCurrentOwner() && generation === loadGenerationRef.current) setIsLoading(false)
    }
  }, [authToken, resumeId, canRecoverForOwner, isCurrentOwner])

  const sessionsLoadedRef = useRef(false)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      loadGenerationRef.current += 1
      readGenerationRef.current = null
      sessionsLoadedRef.current = false
    }
  }, [])
  useEffect(() => {
    if (!canRecoverForOwner() || sessionsLoadedRef.current) return
    sessionsLoadedRef.current = true
    void loadSessions()
  }, [ownerScope.authReady, canRecoverForOwner, loadSessions, isLoading])

  // When generation job completes, reload sessions to get saved questions
  useEffect(() => {
    if (!canRecoverForOwner()) return
    if (jobStream.status === 'completed' && activeJobId) {
      completionRefreshPendingRef.current = true
      activeJobIdRef.current = null
      setActiveJobId(null)
      loadSessions()
    } else if ((jobStream.status === 'failed' || jobStream.status === 'cancelled') && activeJobId) {
      activeJobIdRef.current = null
      setActiveJobId(null)
      if (jobStream.status === 'failed') toast.error('Interview question generation failed')
    } else if (completionRefreshPendingRef.current && readGenerationRef.current === null) {
      void loadSessions()
    }
  }, [jobStream.status, activeJobId, canRecoverForOwner, loadSessions, ownerScope.authReady, isLoading])

  const handleGenerate = async () => {
    if (!canActForOwner() || !canRef.current('e02') || generatingRef.current || activeJobIdRef.current !== null) return
    generatingRef.current = true
    setIsGenerating(true)
    const request = {
      resume_id: resumeId,
      job_description: jobDescription.trim() || undefined,
      company_name: companyName.trim() || undefined,
      role_title: roleTitleInput.trim() || undefined,
    }
    try {
      const resp = await apiClient.generateInterviewPrep(request, {
        authToken: authToken!,
        isCurrent: () => canActForOwner() && canRef.current('e02'),
      })
      if (!isCurrentOwner()) return
      // A list admitted before this mutation cannot erase its new placeholder.
      loadGenerationRef.current += 1
      readGenerationRef.current = null
      setIsLoading(false)
      activeJobIdRef.current = resp.job_id
      setActiveJobId(resp.job_id)
      selectSession(resp.prep_id)
      // Add a placeholder session so progress is visible.
      const placeholder: InterviewPrepResponse = {
        id: resp.prep_id,
        user_id: null,
        resume_id: resumeId,
        job_description: request.job_description ?? null,
        company_name: request.company_name ?? null,
        role_title: request.role_title ?? null,
        questions: [],
        generation_job_id: resp.job_id,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      generationPlaceholdersRef.current.set(placeholder.id, placeholder)
      const nextSessions = [placeholder, ...sessionsRef.current]
      sessionsRef.current = nextSessions
      setSessions(nextSessions)
      if (completionRefreshPendingRef.current) void loadSessions()
    } catch (e) {
      if (isCurrentOwner()) toast.error(e instanceof Error ? e.message : 'Failed to start generation')
    } finally {
      if (isCurrentOwner()) { generatingRef.current = false; setIsGenerating(false) }
    }
  }

  const handleDelete = async (prepId: string) => {
    if (!canRecoverForOwner() || deletingRef.current.has(prepId) || !sessionsRef.current.some(session => session.id === prepId)) return
    deletingRef.current.add(prepId)
    try {
      await apiClient.deleteInterviewPrep(prepId, { authToken: authToken!, isCurrent: canRecoverForOwner })
      if (!isCurrentOwner()) return
      // Invalidate older reads; they may still contain the deleted prep.
      loadGenerationRef.current += 1
      readGenerationRef.current = null
      deletedPrepIdsRef.current.add(prepId)
      generationPlaceholdersRef.current.delete(prepId)
      setIsLoading(false)
      const remaining = sessionsRef.current.filter(session => session.id !== prepId)
      sessionsRef.current = remaining
      setSessions(remaining)
      if (selectedSessionIdRef.current === prepId) selectSession(remaining[0]?.id ?? null)
      toast.success('Deleted')
      if (completionRefreshPendingRef.current) void loadSessions()
    } catch {
      if (isCurrentOwner()) toast.error('Failed to delete')
    } finally {
      if (isCurrentOwner()) deletingRef.current.delete(prepId)
    }
  }

  const updateDraft = (update: (value: string) => void) => (value: string) => {
    if (isCurrentOwner()) update(value)
  }

  const isJobRunning = activeJobId !== null
  const currentSession = sessions.find(s => s.id === selectedSessionId) ?? null
  const questionsByCategory = currentSession?.questions?.reduce<Record<string, InterviewQuestion[]>>(
    (acc, q) => {
      const cat = q.category || 'behavioral'
      if (!acc[cat]) acc[cat] = []
      acc[cat].push(q)
      return acc
    },
    {}
  ) ?? {}

  const categoryCount = (cat: QuestionCategory) => questionsByCategory[cat]?.length ?? 0

  // ─── Empty state ─────────────────────────────────────────────────────────

  if (isLoading && sessions.length === 0) {
    return (
      <div role="status" className="flex h-full items-center justify-center px-4 py-8 text-center text-[11px] text-fg-3">
        Loading interview-prep sessions…
      </div>
    )
  }

  if (!isLoading && loadError && sessions.length === 0) {
    return (
      <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 px-4 py-8 text-center">
        <p className="text-[11px] text-err">{loadError}</p>
        <button
          type="button"
          onClick={() => void loadSessions()}
          className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!isLoading && sessions.length === 0 && !isJobRunning) {
    return (
      <div className="flex h-full flex-col">
        <GenerateForm
          jobDescription={jobDescription}
          setJobDescription={updateDraft(setJobDescription)}
          companyName={companyName}
          setCompanyName={updateDraft(setCompanyName)}
          roleTitle={roleTitleInput}
          setRoleTitle={updateDraft(setRoleTitleInput)}
          onGenerate={handleGenerate}
          isGenerating={isGenerating}
          canGenerate={canGenerate}
          availabilityLoading={entitlementsLoading}
        />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {loadError && <div role="alert" className="shrink-0 px-3 py-2 text-[11px] text-err">
        {loadError} <button type="button" onClick={() => void loadSessions()} className="underline">Retry</button>
      </div>}
      {/* Header: session selector + controls */}
      <div className="shrink-0 border-b border-line bg-surface px-3 py-2 space-y-2">
        {sessions.length > 0 && (
          <select
            value={selectedSessionId ?? ''}
            onChange={e => selectSession(e.target.value)}
            className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-1.5 text-[11px] text-fg-2 outline-none"
          >
            {sessions.map((s, i) => (
              <option key={s.id} value={s.id}>
                Session {sessions.length - i} — {s.role_title || s.company_name || new Date(s.created_at).toLocaleDateString()}
              </option>
            ))}
          </select>
        )}
        <div className="flex items-center gap-2">
          {canGenerate && <button
            onClick={() => { if (canActForOwner() && canRef.current('e02') && activeJobIdRef.current === null) selectSession(null) }}
            className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1 text-[10px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
            title="Generate new set"
          >
            <RefreshCw size={10} />
            New
          </button>}
          {currentSession && (
            <button
              onClick={() => handleDelete(currentSession.id)}
              className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1 text-[10px] font-medium text-fg-3 transition hover:bg-err/10 hover:text-err"
              title="Delete this session"
            >
              <Trash2 size={10} />
              Delete
            </button>
          )}
        </div>
      </div>

      {/* Progress bar when generating */}
      {isJobRunning && (
        <div className="shrink-0 border-b border-line px-3 py-2.5 space-y-1.5">
          <div className="flex items-center gap-2 text-[11px] text-fg-2">
            <Loader2 size={11} className="animate-spin text-accent-strong" />
            <span>{jobStream.message || 'Generating questions…'}</span>
            <span className="ml-auto tabular-nums text-fg-3">{jobStream.percent}%</span>
          </div>
          <div className="h-[3px] w-full overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full rounded-full bg-accent transition-all duration-500"
              style={{ width: `${jobStream.percent}%` }}
            />
          </div>
        </div>
      )}

      {/* Generate form if no session selected */}
      {selectedSessionId === null && (
        <GenerateForm
          jobDescription={jobDescription}
          setJobDescription={updateDraft(setJobDescription)}
          companyName={companyName}
          setCompanyName={updateDraft(setCompanyName)}
          roleTitle={roleTitleInput}
          setRoleTitle={updateDraft(setRoleTitleInput)}
          onGenerate={handleGenerate}
          isGenerating={isGenerating}
          canGenerate={canGenerate}
          availabilityLoading={entitlementsLoading}
        />
      )}

      {/* Questions when session is selected */}
      {currentSession && currentSession.questions.length > 0 && (
        <>
          <div className="shrink-0 border-b border-line bg-accent-soft px-3 py-2 text-[10px] leading-relaxed text-fg-2">
            Practice each answer aloud in the suggested time. Latexy does not record,
            transcribe, or rate your audio/video, and this is not a live employer screening.
          </div>
          <InterviewSimulation key={currentSession.id} prepId={currentSession.id} questions={currentSession.questions}
            authToken={authToken}
            isCurrentSession={() => isCurrentOwner() && selectedSessionIdRef.current === currentSession.id}
            canActForOwner={canActForOwner} />
          {/* Category tabs */}
          <div className="flex shrink-0 gap-0.5 overflow-x-auto border-b border-line bg-surface px-2 py-1.5">
            {CATEGORIES.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => { if (isCurrentOwner()) setActiveCategory(key) }}
                className={`flex shrink-0 items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1 text-[10px] font-medium transition whitespace-nowrap ${
                  activeCategory === key
                    ? 'bg-surface-2 text-fg'
                    : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                <Icon size={10} />
                {label}
                {categoryCount(key) > 0 && (
                  <span className={`rounded-full px-1 text-[9px] font-bold ${
                    activeCategory === key ? 'bg-surface-2 text-fg-2' : 'bg-surface-2 text-fg-3'
                  }`}>
                    {categoryCount(key)}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Questions list */}
          <div className="min-h-0 flex-1 overflow-y-auto p-3 space-y-3">
            {(questionsByCategory[activeCategory] ?? []).length === 0 ? (
              <p className="text-center text-[11px] text-fg-3 py-6">No questions in this category</p>
            ) : (
              (questionsByCategory[activeCategory] ?? []).map((q, i) => (
                <QuestionCard key={q.question} q={q} index={i} />
              ))
            )}
          </div>
        </>
      )}

      {/* Empty questions state for existing session */}
      {currentSession && currentSession.questions.length === 0 && !isJobRunning && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-8">
          <p className="text-center text-[11px] text-fg-3">No questions yet — try generating again.</p>
        </div>
      )}
    </div>
  )
}

// ─── Generate form sub-component ─────────────────────────────────────────────

function GenerateForm({
  jobDescription, setJobDescription,
  companyName, setCompanyName,
  roleTitle, setRoleTitle,
  onGenerate, isGenerating, canGenerate, availabilityLoading,
}: {
  jobDescription: string
  setJobDescription: (v: string) => void
  companyName: string
  setCompanyName: (v: string) => void
  roleTitle: string
  setRoleTitle: (v: string) => void
  onGenerate: () => void
  isGenerating: boolean
  canGenerate: boolean
  availabilityLoading: boolean
}) {
  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-lg)] bg-accent-soft ring-1 ring-accent">
          <BrainCircuit size={16} className="text-accent-strong" />
        </div>
        <div>
          <p className="text-sm font-semibold text-fg">AI Screening Prep</p>
          <p className="text-[10px] text-fg-3">JD-derived questions for spoken audio/video-style practice</p>
        </div>
      </div>

      <p className="text-[12px] leading-relaxed text-fg-3">
        Prepare concise, evidence-backed spoken answers to role-specific questions. Each
        question includes what may be assessed, a suggested response time, and a grounded
        answer outline; behavioral questions also include STAR guidance.
      </p>

      <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-[10px] leading-relaxed text-fg-3">
        This is question-and-answer planning only: Latexy does not capture audio or video,
        simulate a specific employer, or predict a hiring result. Avoid entering sensitive
        personal information.{' '}
        <a
          href="https://www.linkedin.com/help/linkedin/answer/a10376002"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent-strong underline-offset-2 hover:underline"
        >
          Learn how LinkedIn describes its AI interviews
        </a>.
      </div>

      <div className="space-y-2">
        <label className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
          Job Description (recommended)
        </label>
        <textarea
          value={jobDescription}
          onChange={e => setJobDescription(e.target.value)}
          placeholder="Paste the job description here for tailored questions…"
          rows={5}
          className="w-full resize-none rounded-[var(--radius-lg)] border border-line bg-surface-2 px-3 py-2.5 text-[12px] text-fg-2 outline-none placeholder:text-fg-3 focus:border-line-2 transition"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3 mb-1">
            Company
          </label>
          <input
            type="text"
            value={companyName}
            onChange={e => setCompanyName(e.target.value)}
            placeholder="e.g. Google"
            className="w-full rounded-[var(--radius-lg)] border border-line bg-surface-2 px-3 py-2 text-[12px] text-fg-2 outline-none placeholder:text-fg-3 focus:border-line-2 transition"
          />
        </div>
        <div>
          <label className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3 mb-1">
            Role
          </label>
          <input
            type="text"
            value={roleTitle}
            onChange={e => setRoleTitle(e.target.value)}
            placeholder="e.g. SWE"
            className="w-full rounded-[var(--radius-lg)] border border-line bg-surface-2 px-3 py-2 text-[12px] text-fg-2 outline-none placeholder:text-fg-3 focus:border-line-2 transition"
          />
        </div>
      </div>

      {!canGenerate && <p role="status" className="text-[11px] text-fg-3">{availabilityLoading ? 'Checking interview-prep availability…' : 'New interview-prep generation is unavailable. Your draft and saved practice remain available.'}</p>}
      {canGenerate && <button
        onClick={onGenerate}
        disabled={isGenerating}
        className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-lg)] bg-accent-soft py-2.5 text-xs font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:opacity-50"
      >
        {isGenerating ? (
          <><Loader2 size={12} className="animate-spin" /> Generating…</>
        ) : (
          <><BrainCircuit size={12} /> Generate Screening Practice</>
        )}
      </button>}
    </div>
  )
}
