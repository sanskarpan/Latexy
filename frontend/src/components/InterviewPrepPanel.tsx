'use client'

import { useState, useEffect, useCallback } from 'react'
import { ChevronDown, ChevronRight, Loader2, RefreshCw, Trash2, BrainCircuit, BookOpen, HelpCircle, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type InterviewPrepResponse, type InterviewQuestion } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'

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

interface InterviewPrepPanelProps {
  resumeId: string
  defaultJobDescription?: string
}

export default function InterviewPrepPanel({ resumeId, defaultJobDescription = '' }: InterviewPrepPanelProps) {
  const [sessions, setSessions] = useState<InterviewPrepResponse[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isGenerating, setIsGenerating] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [jobDescription, setJobDescription] = useState(defaultJobDescription)
  const [companyName, setCompanyName] = useState('')
  const [roleTitleInput, setRoleTitleInput] = useState('')
  const [activeCategory, setActiveCategory] = useState<QuestionCategory>('behavioral')

  const { state: jobStream } = useJobStream(activeJobId)

  // Load existing sessions on mount
  useEffect(() => {
    loadSessions()
  }, [resumeId]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadSessions = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await apiClient.listInterviewPrep(resumeId)
      setSessions(data)
      if (data.length > 0 && !selectedSessionId) {
        setSelectedSessionId(data[0].id)
      }
    } catch {
      // silent
    } finally {
      setIsLoading(false)
    }
  }, [resumeId, selectedSessionId])

  // When generation job completes, reload sessions to get saved questions
  useEffect(() => {
    if (jobStream.status === 'completed' && activeJobId) {
      setActiveJobId(null)
      loadSessions()
    } else if (jobStream.status === 'failed' && activeJobId) {
      setActiveJobId(null)
      toast.error('Interview question generation failed')
    }
  }, [jobStream.status, activeJobId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerate = async () => {
    if (isGenerating) return
    setIsGenerating(true)
    try {
      const resp = await apiClient.generateInterviewPrep({
        resume_id: resumeId,
        job_description: jobDescription.trim() || undefined,
        company_name: companyName.trim() || undefined,
        role_title: roleTitleInput.trim() || undefined,
      })
      setActiveJobId(resp.job_id)
      setSelectedSessionId(resp.prep_id)
      // Add a placeholder session so progress is visible
      setSessions(prev => [{
        id: resp.prep_id,
        user_id: null,
        resume_id: resumeId,
        job_description: jobDescription.trim() || null,
        company_name: companyName.trim() || null,
        role_title: roleTitleInput.trim() || null,
        questions: [],
        generation_job_id: resp.job_id,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }, ...prev])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to start generation')
    } finally {
      setIsGenerating(false)
    }
  }

  const handleDelete = async (prepId: string) => {
    try {
      await apiClient.deleteInterviewPrep(prepId)
      setSessions(prev => prev.filter(s => s.id !== prepId))
      if (selectedSessionId === prepId) {
        const remaining = sessions.filter(s => s.id !== prepId)
        setSelectedSessionId(remaining[0]?.id ?? null)
      }
      toast.success('Deleted')
    } catch {
      toast.error('Failed to delete')
    }
  }

  const isJobRunning = jobStream.status === 'queued' || jobStream.status === 'processing'
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

  if (!isLoading && sessions.length === 0 && !isJobRunning) {
    return (
      <div className="flex h-full flex-col">
        <GenerateForm
          jobDescription={jobDescription}
          setJobDescription={setJobDescription}
          companyName={companyName}
          setCompanyName={setCompanyName}
          roleTitle={roleTitleInput}
          setRoleTitle={setRoleTitleInput}
          onGenerate={handleGenerate}
          isGenerating={isGenerating}
        />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header: session selector + controls */}
      <div className="shrink-0 border-b border-line bg-surface px-3 py-2 space-y-2">
        {sessions.length > 0 && (
          <select
            value={selectedSessionId ?? ''}
            onChange={e => setSelectedSessionId(e.target.value)}
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
          <button
            onClick={() => setSelectedSessionId(null)}
            className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1 text-[10px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
            title="Generate new set"
          >
            <RefreshCw size={10} />
            New
          </button>
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
          setJobDescription={setJobDescription}
          companyName={companyName}
          setCompanyName={setCompanyName}
          roleTitle={roleTitleInput}
          setRoleTitle={setRoleTitleInput}
          onGenerate={handleGenerate}
          isGenerating={isGenerating}
        />
      )}

      {/* Questions when session is selected */}
      {currentSession && currentSession.questions.length > 0 && (
        <>
          {/* Category tabs */}
          <div className="flex shrink-0 gap-0.5 overflow-x-auto border-b border-line bg-surface px-2 py-1.5">
            {CATEGORIES.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setActiveCategory(key)}
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
  onGenerate, isGenerating,
}: {
  jobDescription: string
  setJobDescription: (v: string) => void
  companyName: string
  setCompanyName: (v: string) => void
  roleTitle: string
  setRoleTitle: (v: string) => void
  onGenerate: () => void
  isGenerating: boolean
}) {
  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-lg)] bg-accent-soft ring-1 ring-accent">
          <BrainCircuit size={16} className="text-accent-strong" />
        </div>
        <div>
          <p className="text-sm font-semibold text-fg">Interview Prep</p>
          <p className="text-[10px] text-fg-3">AI-generated questions with STAR hints</p>
        </div>
      </div>

      <p className="text-[12px] leading-relaxed text-fg-3">
        Generate role-specific interview questions based on your resume and the job description.
        Includes behavioral, technical, motivational, and difficult questions.
      </p>

      <div className="space-y-2">
        <label className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
          Job Description (optional)
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

      <button
        onClick={onGenerate}
        disabled={isGenerating}
        className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-lg)] bg-accent-soft py-2.5 text-xs font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:opacity-50"
      >
        {isGenerating ? (
          <><Loader2 size={12} className="animate-spin" /> Generating…</>
        ) : (
          <><BrainCircuit size={12} /> Generate Interview Questions</>
        )}
      </button>
    </div>
  )
}
