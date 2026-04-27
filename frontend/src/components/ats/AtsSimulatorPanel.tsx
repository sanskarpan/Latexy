'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, ChevronDown, ChevronUp, Info, Loader2, Monitor } from 'lucide-react'
import { apiClient } from '@/lib/api-client'

type AtsProfile = { key: string; label: string; tier: string }

type AtsIssue = {
  type: string
  severity: string
  description: string
  line_range: string
}

type SimulationResult = {
  ats_label: string
  plain_text_view: string
  issues: AtsIssue[]
  score: number
  recommendations: string[]
  cached: boolean
}

interface AtsSimulatorPanelProps {
  latexContent: string
}

const TIER_COLORS: Record<string, string> = {
  good: 'text-emerald-400 bg-emerald-400/10 ring-emerald-400/20',
  medium: 'text-amber-400 bg-amber-400/10 ring-amber-400/20',
  poor: 'text-red-400 bg-red-400/10 ring-red-400/20',
}

const SEVERITY_ICON: Record<string, React.ReactNode> = {
  high: <AlertTriangle size={13} className="text-red-400 shrink-0 mt-0.5" />,
  medium: <Info size={13} className="text-amber-400 shrink-0 mt-0.5" />,
  low: <Info size={13} className="text-zinc-500 shrink-0 mt-0.5" />,
}

function ScoreRing({ score }: { score: number }) {
  const color = score >= 80 ? '#34d399' : score >= 60 ? '#fbbf24' : '#f87171'
  const r = 15.9
  const circ = 2 * Math.PI * r
  const dash = (score / 100) * circ
  return (
    <svg width={56} height={56} viewBox="0 0 36 36" className="shrink-0">
      <circle cx="18" cy="18" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="2.5" />
      <circle
        cx="18" cy="18" r={r} fill="none"
        stroke={color} strokeWidth="2.5"
        strokeDasharray={`${dash} ${circ - dash}`}
        strokeLinecap="round"
        transform="rotate(-90 18 18)"
      />
      <text x="18" y="18" dominantBaseline="middle" textAnchor="middle" fontSize="8" fill="white" fontWeight="600">
        {score}
      </text>
    </svg>
  )
}

export default function AtsSimulatorPanel({ latexContent }: AtsSimulatorPanelProps) {
  const [profiles, setProfiles] = useState<AtsProfile[]>([])
  const [selectedAts, setSelectedAts] = useState<string | null>(null)
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [recsOpen, setRecsOpen] = useState(false)
  const [textOpen, setTextOpen] = useState(false)

  useEffect(() => {
    apiClient.getAtsSimulatorProfiles()
      .then(data => setProfiles(data.profiles))
      .catch(() => {})
  }, [])

  const runSimulation = async () => {
    if (!selectedAts || !latexContent.trim()) return
    setIsLoading(true)
    setError(null)
    setResult(null)
    setRecsOpen(false)
    setTextOpen(false)
    try {
      const data = await apiClient.simulateAts({ latex_content: latexContent, ats_name: selectedAts })
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Simulation failed')
    } finally {
      setIsLoading(false)
    }
  }

  const tierLabel = (tier: string) => tier.charAt(0).toUpperCase() + tier.slice(1)

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400 mb-3">
          Select ATS System
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {profiles.map(p => (
            <button
              key={p.key}
              onClick={() => { setSelectedAts(p.key); setResult(null) }}
              className={`flex flex-col gap-1.5 rounded-lg border p-3 text-left transition ${
                selectedAts === p.key
                  ? 'border-orange-400/40 bg-orange-400/10'
                  : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
              }`}
            >
              <span className="text-xs font-semibold text-zinc-200 leading-tight">{p.label}</span>
              <span
                className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${
                  TIER_COLORS[p.tier] ?? 'text-zinc-400 bg-zinc-400/10 ring-zinc-400/20'
                }`}
              >
                {tierLabel(p.tier)}
              </span>
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={runSimulation}
        disabled={!selectedAts || isLoading || !latexContent.trim()}
        className="flex items-center gap-2 rounded-lg bg-orange-500/20 px-4 py-2.5 text-sm font-semibold text-orange-200 ring-1 ring-orange-400/20 transition hover:bg-orange-500/30 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? <Loader2 size={14} className="animate-spin" /> : <Monitor size={14} />}
        {isLoading ? 'Simulating…' : 'Simulate'}
      </button>

      {error && (
        <div className="rounded-lg border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-4">
          {/* Score header */}
          <div className="flex items-center gap-4 rounded-lg border border-white/10 bg-white/[0.03] p-4">
            <ScoreRing score={result.score} />
            <div className="min-w-0 flex-1">
              <p className="text-base font-semibold text-white">{result.ats_label}</p>
              <p className="text-sm text-zinc-400">
                Compatibility score: <span className="font-semibold text-white">{result.score}/100</span>
              </p>
              {result.issues.length === 0 && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-emerald-400">
                  <CheckCircle size={12} />
                  No issues detected
                </p>
              )}
            </div>
          </div>

          {/* Issues list */}
          {result.issues.length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">
                Issues ({result.issues.length})
              </h4>
              <div className="space-y-2">
                {result.issues.map((issue, i) => (
                  <div key={i} className="flex gap-2.5 rounded-lg border border-white/10 bg-white/[0.03] p-3">
                    {SEVERITY_ICON[issue.severity] ?? SEVERITY_ICON.low}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold text-zinc-200">{issue.type.replace(/_/g, ' ')}</span>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${
                          issue.severity === 'high'
                            ? 'text-red-400 bg-red-400/10 ring-red-400/20'
                            : issue.severity === 'medium'
                            ? 'text-amber-400 bg-amber-400/10 ring-amber-400/20'
                            : 'text-zinc-500 bg-zinc-500/10 ring-zinc-500/20'
                        }`}>
                          {issue.severity}
                        </span>
                        {issue.line_range && (
                          <span className="text-[10px] text-zinc-600 font-mono">{issue.line_range}</span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-zinc-400 leading-relaxed">{issue.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommendations accordion */}
          {result.recommendations.length > 0 && (
            <div className="rounded-lg border border-white/10 bg-white/[0.03] overflow-hidden">
              <button
                onClick={() => setRecsOpen(v => !v)}
                className="flex w-full items-center justify-between px-4 py-3 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400 hover:text-zinc-200 transition"
              >
                <span>Recommendations ({result.recommendations.length})</span>
                {recsOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </button>
              {recsOpen && (
                <div className="border-t border-white/5 px-4 py-3 space-y-2">
                  {result.recommendations.map((rec, i) => (
                    <div key={i} className="flex gap-2 text-xs text-zinc-300">
                      <span className="text-zinc-600 shrink-0">•</span>
                      <span>{rec}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Plain text view accordion */}
          <div className="rounded-lg border border-white/10 bg-white/[0.03] overflow-hidden">
            <button
              onClick={() => setTextOpen(v => !v)}
              className="flex w-full items-center justify-between px-4 py-3 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400 hover:text-zinc-200 transition"
            >
              <span>ATS Plain-Text View</span>
              {textOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
            {textOpen && (
              <div className="border-t border-white/5">
                <pre className="overflow-x-auto whitespace-pre-wrap break-words p-4 text-[11px] leading-relaxed text-zinc-300 font-mono max-h-96 overflow-y-auto">
                  {result.plain_text_view || '(empty)'}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
