'use client'

import { useState } from 'react'
import { Loader2, Search } from 'lucide-react'
import { apiClient } from '@/lib/api-client'

type KeywordEntry = {
  keyword: string
  status: 'present' | 'partial' | 'missing'
  count: number
  required: boolean
  suggested_location: string | null
}

type DensityResult = {
  keywords: KeywordEntry[]
  coverage_score: number
}

interface KeywordDensityMapProps {
  latexContent: string
}

const STATUS_STYLES: Record<string, string> = {
  present: 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30',
  partial: 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30',
  missing: 'bg-rose-500/20 text-rose-300 ring-1 ring-rose-500/30',
}

const STATUS_ICONS: Record<string, string> = {
  present: '✓',
  partial: '~',
  missing: '✗',
}

export default function KeywordDensityMap({ latexContent }: KeywordDensityMapProps) {
  const [jobDescription, setJobDescription] = useState('')
  const [result, setResult] = useState<DensityResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tooltip, setTooltip] = useState<{ keyword: string; location: string } | null>(null)

  const runAnalysis = async () => {
    if (!jobDescription.trim() || !latexContent.trim()) return
    setIsLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await apiClient.keywordDensity({
        resume_latex: latexContent,
        job_description: jobDescription,
      })
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setIsLoading(false)
    }
  }

  const present = result?.keywords.filter(k => k.status === 'present').length ?? 0
  const partial = result?.keywords.filter(k => k.status === 'partial').length ?? 0
  const missing = result?.keywords.filter(k => k.status === 'missing').length ?? 0

  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">
          Job Description
        </label>
        <textarea
          value={jobDescription}
          onChange={e => setJobDescription(e.target.value)}
          placeholder="Paste the job description to see which keywords your resume covers…"
          className="scrollbar-subtle h-36 w-full resize-none rounded-xl border border-white/10 bg-black/40 p-3 text-sm text-zinc-100 outline-none transition focus:border-orange-300/40"
        />
      </div>

      <button
        onClick={runAnalysis}
        disabled={isLoading || !jobDescription.trim() || !latexContent.trim()}
        className="flex items-center gap-2 rounded-lg bg-orange-500/20 px-4 py-2.5 text-sm font-semibold text-orange-200 ring-1 ring-orange-400/20 transition hover:bg-orange-500/30 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
        {isLoading ? 'Analyzing…' : 'Analyze Keywords'}
      </button>

      {error && (
        <div className="rounded-lg border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-4">
          {/* Coverage progress bar */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs font-semibold text-zinc-400">Keyword Coverage</span>
              <span className="text-sm font-semibold text-white">{result.coverage_score}%</span>
            </div>
            <div className="h-2 rounded-full bg-white/10">
              <div
                className={`h-full rounded-full transition-all ${
                  result.coverage_score >= 70
                    ? 'bg-emerald-400'
                    : result.coverage_score >= 40
                    ? 'bg-amber-400'
                    : 'bg-rose-400'
                }`}
                style={{ width: `${result.coverage_score}%` }}
              />
            </div>
            <div className="mt-2 flex gap-4 text-[11px] text-zinc-500">
              <span><span className="text-emerald-400 font-semibold">{present}</span> present</span>
              <span><span className="text-amber-400 font-semibold">{partial}</span> partial</span>
              <span><span className="text-rose-400 font-semibold">{missing}</span> missing</span>
            </div>
          </div>

          {/* Tag cloud */}
          <div className="flex flex-wrap gap-2">
            {result.keywords.map((kw, i) => (
              <div key={i} className="relative">
                <button
                  onClick={() => {
                    if (kw.status === 'missing' && kw.suggested_location) {
                      setTooltip(tooltip?.keyword === kw.keyword ? null : {
                        keyword: kw.keyword,
                        location: kw.suggested_location,
                      })
                    }
                  }}
                  className={`flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition ${
                    STATUS_STYLES[kw.status]
                  } ${kw.status === 'missing' ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}
                  title={
                    kw.status === 'present'
                      ? `Found ${kw.count} time${kw.count !== 1 ? 's' : ''}`
                      : kw.status === 'partial'
                      ? 'Stem match found'
                      : `Missing — click for suggestion`
                  }
                >
                  <span className="font-bold opacity-70">{STATUS_ICONS[kw.status]}</span>
                  {kw.keyword}
                </button>

                {/* Tooltip for missing keywords */}
                {tooltip?.keyword === kw.keyword && kw.suggested_location && (
                  <div className="absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 whitespace-nowrap rounded-lg border border-white/10 bg-zinc-900 px-3 py-2 text-[11px] text-zinc-300 shadow-lg">
                    Suggested: <span className="font-semibold text-white">{kw.suggested_location}</span>
                    <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-zinc-900" />
                  </div>
                )}
              </div>
            ))}
          </div>

          {result.keywords.length === 0 && (
            <p className="text-sm text-zinc-500">No keywords extracted from the job description.</p>
          )}
        </div>
      )}
    </div>
  )
}
