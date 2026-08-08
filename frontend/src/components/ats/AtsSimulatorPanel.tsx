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
  getLatexContent: () => string
}

const TIER_COLORS: Record<string, string> = {
  good: 'text-ok bg-ok/10 ring-ok/20',
  medium: 'text-warn bg-warn/10 ring-warn/20',
  poor: 'text-err bg-err/10 ring-err/20',
}

const SEVERITY_ICON: Record<string, React.ReactNode> = {
  high: <AlertTriangle size={13} className="text-err shrink-0 mt-0.5" />,
  medium: <Info size={13} className="text-warn shrink-0 mt-0.5" />,
  low: <Info size={13} className="text-fg-3 shrink-0 mt-0.5" />,
}

function ScoreRing({ score }: { score: number }) {
  const color = score >= 80 ? 'var(--ok)' : score >= 60 ? 'var(--warn)' : 'var(--err)'
  const r = 15.9
  const circ = 2 * Math.PI * r
  const dash = (score / 100) * circ
  return (
    <svg width={56} height={56} viewBox="0 0 36 36" className="shrink-0">
      <circle cx="18" cy="18" r={r} fill="none" stroke="var(--line)" strokeWidth="2.5" />
      <circle
        cx="18" cy="18" r={r} fill="none"
        stroke={color} strokeWidth="2.5"
        strokeDasharray={`${dash} ${circ - dash}`}
        strokeLinecap="round"
        transform="rotate(-90 18 18)"
      />
      <text x="18" y="18" dominantBaseline="middle" textAnchor="middle" fontSize="8" fill="var(--fg)" fontWeight="600">
        {score}
      </text>
    </svg>
  )
}

export default function AtsSimulatorPanel({ getLatexContent }: AtsSimulatorPanelProps) {
  const [profiles, setProfiles] = useState<AtsProfile[]>([])
  const [selectedAts, setSelectedAts] = useState<string | null>(null)
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [recsOpen, setRecsOpen] = useState(false)
  const [textOpen, setTextOpen] = useState(false)

  useEffect(() => {
    apiClient.getAtsSimulatorProfiles()
      .then(data => { setProfiles(data.profiles); setError(null) })
      .catch(() => setError('Failed to load ATS systems. Please refresh to try again.'))
  }, [])

  const runSimulation = async () => {
    const latexContent = getLatexContent()
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
        <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2 mb-3">
          Select ATS System
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {profiles.map(p => (
            <button
              key={p.key}
              onClick={() => { setSelectedAts(p.key); setResult(null) }}
              className={`flex flex-col gap-1.5 rounded-[var(--radius-md)] border p-3 text-left transition ${
                selectedAts === p.key
                  ? 'border-accent bg-accent-soft'
                  : 'border-line bg-surface hover:border-line-2 hover:bg-surface-2'
              }`}
            >
              <span className="text-xs font-semibold text-fg leading-tight">{p.label}</span>
              <span
                className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${
                  TIER_COLORS[p.tier] ?? 'text-fg-2 bg-surface-2 ring-line'
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
        disabled={!selectedAts || isLoading}
        className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2.5 text-sm font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? <Loader2 size={14} className="animate-spin" /> : <Monitor size={14} />}
        {isLoading ? 'Simulating…' : 'Simulate'}
      </button>

      {error && (
        <div className="rounded-[var(--radius-md)] border border-err/20 bg-err/10 px-4 py-3 text-sm text-err">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-4">
          {/* Score header */}
          <div className="flex items-center gap-4 rounded-[var(--radius-md)] border border-line bg-surface p-4">
            <ScoreRing score={result.score} />
            <div className="min-w-0 flex-1">
              <p className="text-base font-semibold text-fg">{result.ats_label}</p>
              <p className="text-sm text-fg-2">
                Compatibility score: <span className="font-semibold text-fg">{result.score}/100</span>
              </p>
              {result.issues.length === 0 && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-ok">
                  <CheckCircle size={12} />
                  No issues detected
                </p>
              )}
            </div>
          </div>

          {/* Issues list */}
          {result.issues.length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
                Issues ({result.issues.length})
              </h4>
              <div className="space-y-2">
                {result.issues.map((issue, i) => (
                  <div key={i} className="flex gap-2.5 rounded-[var(--radius-md)] border border-line bg-surface p-3">
                    {SEVERITY_ICON[issue.severity] ?? SEVERITY_ICON.low}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold text-fg">{issue.type.replace(/_/g, ' ')}</span>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${
                          issue.severity === 'high'
                            ? 'text-err bg-err/10 ring-err/20'
                            : issue.severity === 'medium'
                            ? 'text-warn bg-warn/10 ring-warn/20'
                            : 'text-fg-3 bg-surface-2 ring-line'
                        }`}>
                          {issue.severity}
                        </span>
                        {issue.line_range && (
                          <span className="text-[10px] text-fg-3 font-mono">{issue.line_range}</span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-fg-2 leading-relaxed">{issue.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommendations accordion */}
          {result.recommendations.length > 0 && (
            <div className="rounded-[var(--radius-md)] border border-line bg-surface overflow-hidden">
              <button
                onClick={() => setRecsOpen(v => !v)}
                className="flex w-full items-center justify-between px-4 py-3 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2 hover:text-fg transition"
              >
                <span>Recommendations ({result.recommendations.length})</span>
                {recsOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </button>
              {recsOpen && (
                <div className="border-t border-line px-4 py-3 space-y-2">
                  {result.recommendations.map((rec, i) => (
                    <div key={i} className="flex gap-2 text-xs text-fg-2">
                      <span className="text-fg-3 shrink-0">•</span>
                      <span>{rec}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Plain text view accordion */}
          <div className="rounded-[var(--radius-md)] border border-line bg-surface overflow-hidden">
            <button
              onClick={() => setTextOpen(v => !v)}
              className="flex w-full items-center justify-between px-4 py-3 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2 hover:text-fg transition"
            >
              <span>ATS Plain-Text View</span>
              {textOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
            {textOpen && (
              <div className="border-t border-line">
                <pre className="overflow-x-auto whitespace-pre-wrap break-words p-4 text-[11px] leading-relaxed text-fg-2 font-mono max-h-96 overflow-y-auto">
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
