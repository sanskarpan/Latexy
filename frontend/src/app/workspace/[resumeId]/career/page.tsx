'use client'

/**
 * Career Path + Skills Gap Analysis page — Feature 80.
 *
 * /workspace/[resumeId]/career
 *
 * UI flow:
 *  1. Target role autocomplete search
 *  2. "Analyze" button → POST /career/analyze (with progress steps)
 *  3. Results: CareerPathChart (graph) + SkillsGapPanel (skills + LLM plan)
 *  4. Past analyses listed below
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import {
  ArrowLeft,
  ChevronRight,
  Loader2,
  Search,
  Sparkles,
  TrendingUp,
  Clock,
  ChevronDown,
} from 'lucide-react'
import {
  apiClient,
  type CareerAnalysisResponse,
  type CareerRoleResponse,
} from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import CareerPathChart from '@/components/CareerPathChart'
import SkillsGapPanel from '@/components/SkillsGapPanel'

// ── Progress steps ─────────────────────────────────────────────────────────────

const STEPS = [
  { key: 'parse',   label: 'Parsing resume…' },
  { key: 'skills',  label: 'Analysing skills…' },
  { key: 'path',    label: 'Building career path…' },
  { key: 'gap',     label: 'Running gap analysis…' },
]

// ── Page ───────────────────────────────────────────────────────────────────────

export default function CareerPathPage() {
  const params = useParams()
  const resumeId = params.resumeId as string
  const { data: session } = useSession()

  // Search
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<CareerRoleResponse[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const suggestTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Analysis state
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [stepIdx, setStepIdx] = useState(0)
  const [analysis, setAnalysis] = useState<CareerAnalysisResponse | null>(null)
  const [pastAnalyses, setPastAnalyses] = useState<CareerAnalysisResponse[]>([])
  const [pastLoading, setPastLoading] = useState(true)
  const [expandedPastId, setExpandedPastId] = useState<string | null>(null)
  const [expandedPastData, setExpandedPastData] = useState<CareerAnalysisResponse | null>(null)

  // Load past analyses
  useEffect(() => {
    if (!session?.session?.token) return
    apiClient.listCareerAnalyses(resumeId)
      .then(setPastAnalyses)
      .catch(() => {})
      .finally(() => setPastLoading(false))
  }, [resumeId, session])

  // Autocomplete
  const fetchSuggestions = useCallback(async (q: string) => {
    if (!q.trim()) { setSuggestions([]); return }
    try {
      const roles = await apiClient.searchCareerRoles(q)
      setSuggestions(roles)
    } catch {
      setSuggestions([])
    }
  }, [])

  const handleQueryChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setQuery(val)
    setShowSuggestions(true)
    if (suggestTimeout.current) clearTimeout(suggestTimeout.current)
    suggestTimeout.current = setTimeout(() => fetchSuggestions(val), 250)
  }

  const handleSelectSuggestion = (role: CareerRoleResponse) => {
    setQuery(role.title)
    setSuggestions([])
    setShowSuggestions(false)
  }

  // Run analysis
  const handleAnalyze = async () => {
    if (!query.trim()) {
      toast.error('Enter a target role title')
      return
    }
    if (!session?.session?.token) {
      toast.error('Please sign in to run an analysis')
      return
    }

    setIsAnalyzing(true)
    setStepIdx(0)
    setAnalysis(null)

    // Simulate progress steps (each takes ~25% of expected time)
    const stepInterval = setInterval(() => {
      setStepIdx((prev) => Math.min(prev + 1, STEPS.length - 1))
    }, 1800)

    try {
      const result = await apiClient.analyzeCareerPath(resumeId, query.trim())
      clearInterval(stepInterval)
      setAnalysis(result)
      setPastAnalyses((prev) => [result, ...prev])
      toast.success('Career analysis complete!')
    } catch (err: unknown) {
      clearInterval(stepInterval)
      const msg = err instanceof Error ? err.message : 'Analysis failed'
      toast.error(msg)
    } finally {
      setIsAnalyzing(false)
    }
  }

  // Expand a past analysis
  const handleExpandPast = async (id: string) => {
    if (expandedPastId === id) {
      setExpandedPastId(null)
      setExpandedPastData(null)
      return
    }
    setExpandedPastId(id)
    try {
      const data = await apiClient.getCareerAnalysis(id)
      setExpandedPastData(data)
    } catch {
      toast.error('Could not load analysis details')
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-[#09090b] text-sm text-zinc-300">
      {/* Header */}
      <header className="flex h-12 items-center gap-3 border-b border-white/[0.05] bg-[#0a0a0a] px-4">
        <Link
          href={`/workspace/${resumeId}/edit`}
          className="flex items-center gap-1.5 text-[11px] text-zinc-600 transition hover:text-zinc-300"
        >
          <ArrowLeft size={13} />
          Back to editor
        </Link>
        <ChevronRight size={11} className="text-zinc-800" />
        <span className="text-[11px] font-semibold text-zinc-400">Career Path</span>
        <div className="ml-auto flex items-center gap-1.5 text-[11px] text-zinc-700">
          <TrendingUp size={12} />
          Feature 80
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-6 py-8">
        {/* Title */}
        <div className="mb-8">
          <h1 className="text-xl font-bold text-zinc-100">Career Path Visualization</h1>
          <p className="mt-1 text-[12px] text-zinc-600">
            Enter a target role and we&apos;ll map the path from your current position,
            identify skills gaps, and generate a personalized development plan.
          </p>
        </div>

        {/* Search + Analyze */}
        <div className="mb-8 rounded-xl border border-white/[0.06] bg-white/[0.02] p-5">
          <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
            Target Role
          </label>
          <div className="relative">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" />
                <input
                  value={query}
                  onChange={handleQueryChange}
                  onFocus={() => setShowSuggestions(true)}
                  onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                  placeholder="e.g. Staff Software Engineer, Principal Data Scientist…"
                  className="w-full rounded-lg border border-white/[0.06] bg-black/30 py-2 pl-8 pr-3 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-700 focus:border-violet-500/30 focus:ring-1 focus:ring-violet-500/20"
                  disabled={isAnalyzing}
                />
                {/* Autocomplete dropdown */}
                {showSuggestions && suggestions.length > 0 && (
                  <div className="absolute left-0 right-0 top-full z-20 mt-1 overflow-hidden rounded-lg border border-white/[0.06] bg-[#111] shadow-xl">
                    {suggestions.map((role) => (
                      <button
                        key={role.id}
                        onMouseDown={() => handleSelectSuggestion(role)}
                        className="flex w-full items-center gap-3 px-3 py-2 text-left text-[11px] transition hover:bg-white/[0.06]"
                      >
                        <span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-600">
                          {role.level}
                        </span>
                        <span className="text-zinc-300">{role.title}</span>
                        <span className="ml-auto text-zinc-700">
                          {role.industry.replace(/_/g, ' ')}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={handleAnalyze}
                disabled={isAnalyzing || !query.trim()}
                className="flex items-center gap-1.5 rounded-lg border border-violet-400/20 bg-gradient-to-r from-violet-500/15 to-orange-500/10 px-4 py-2 text-[12px] font-semibold text-violet-200 transition hover:from-violet-500/25 hover:to-orange-500/15 disabled:opacity-40"
              >
                {isAnalyzing ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                {isAnalyzing ? 'Analyzing…' : 'Analyze'}
              </button>
            </div>
          </div>

          {/* Progress steps */}
          {isAnalyzing && (
            <div className="mt-4 space-y-2">
              {STEPS.map((step, i) => (
                <div key={step.key} className="flex items-center gap-2 text-[11px]">
                  {i < stepIdx ? (
                    <span className="text-emerald-500">✓</span>
                  ) : i === stepIdx ? (
                    <Loader2 size={11} className="animate-spin text-violet-400" />
                  ) : (
                    <span className="text-zinc-800">○</span>
                  )}
                  <span className={i <= stepIdx ? 'text-zinc-400' : 'text-zinc-800'}>
                    {step.label}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Results */}
        {analysis && (
          <div className="mb-8 space-y-6">
            <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-5">
              <h2 className="mb-4 text-[13px] font-bold text-zinc-200">Career Path</h2>
              {analysis.path_roles && analysis.path_roles.length > 0 ? (
                <CareerPathChart
                  pathRoles={analysis.path_roles}
                  targetRole={analysis.target_role ?? null}
                />
              ) : (
                <p className="text-[12px] text-zinc-600">
                  No matching path found in the career graph — see the plan below.
                </p>
              )}
            </div>

            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-5">
              <SkillsGapPanel analysis={analysis} />
            </div>
          </div>
        )}

        {/* Past analyses */}
        <div>
          <h2 className="mb-3 text-[12px] font-semibold text-zinc-500">Past Analyses</h2>
          {pastLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 size={16} className="animate-spin text-zinc-700" />
            </div>
          ) : pastAnalyses.length === 0 ? (
            <div className="rounded-xl border border-white/[0.04] bg-white/[0.01] py-8 text-center text-[12px] text-zinc-700">
              No analyses yet. Run your first analysis above.
            </div>
          ) : (
            <div className="space-y-2">
              {pastAnalyses.map((pa) => {
                const targetTitle =
                  pa.target_role?.title ?? pa.target_role_freetext ?? 'Unknown target'
                const years = pa.timeline_months
                  ? Math.round((pa.timeline_months / 12) * 10) / 10
                  : null
                const isExpanded = expandedPastId === pa.id

                return (
                  <div
                    key={pa.id}
                    className="rounded-xl border border-white/[0.05] bg-white/[0.02]"
                  >
                    <button
                      onClick={() => handleExpandPast(pa.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left"
                    >
                      <TrendingUp size={12} className="shrink-0 text-violet-500" />
                      <span className="flex-1 text-[12px] font-medium text-zinc-300">
                        → {targetTitle}
                      </span>
                      {years && (
                        <span className="flex items-center gap-1 text-[11px] text-zinc-600">
                          <Clock size={10} />
                          ~{years} yr{years !== 1 ? 's' : ''}
                        </span>
                      )}
                      <span className="text-[10px] text-zinc-700">
                        {new Date(pa.created_at).toLocaleDateString()}
                      </span>
                      <ChevronDown
                        size={13}
                        className={`text-zinc-700 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                      />
                    </button>

                    {isExpanded && (
                      <div className="border-t border-white/[0.04] px-4 pb-4 pt-3">
                        {expandedPastData && expandedPastData.id === pa.id ? (
                          <div className="space-y-4">
                            {expandedPastData.path_roles && expandedPastData.path_roles.length > 0 && (
                              <CareerPathChart
                                pathRoles={expandedPastData.path_roles}
                                targetRole={expandedPastData.target_role ?? null}
                              />
                            )}
                            <SkillsGapPanel analysis={expandedPastData} />
                          </div>
                        ) : (
                          <div className="flex justify-center py-4">
                            <Loader2 size={14} className="animate-spin text-zinc-700" />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
