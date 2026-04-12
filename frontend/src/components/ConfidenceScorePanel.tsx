'use client'

import type { ConfidenceScoreResponse } from '@/lib/api-client'

// ── Radar chart (pure SVG, no external dep) ───────────────────────────────────

const AXES = [
  { key: 'writing_quality' as const, label: 'Writing' },
  { key: 'completeness' as const,    label: 'Complete' },
  { key: 'quantification' as const,  label: 'Numbers' },
  { key: 'formatting' as const,      label: 'Format' },
  { key: 'section_order' as const,   label: 'Order' },
]

const clamp = (v: number) => Math.min(100, Math.max(0, v))

function RadarChart({ score }: { score: ConfidenceScoreResponse }) {
  const SIZE = 150
  const CENTER = SIZE / 2
  const RADIUS = SIZE * 0.36
  const n = AXES.length

  const getXY = (i: number, r: number): [number, number] => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2
    return [CENTER + r * Math.cos(angle), CENTER + r * Math.sin(angle)]
  }

  const toPoints = (pts: [number, number][]) =>
    pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')

  const gridPolygon = (frac: number) =>
    toPoints(AXES.map((_, i) => getXY(i, RADIUS * frac)))

  const dataPolygon = toPoints(
    AXES.map(({ key }, i) => getXY(i, (clamp(score[key]) / 100) * RADIUS))
  )

  return (
    <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden>
      {/* Grid rings */}
      {[0.25, 0.5, 0.75, 1].map((t) => (
        <polygon
          key={t}
          points={gridPolygon(t)}
          fill="none"
          stroke="rgba(255,255,255,0.07)"
          strokeWidth="0.5"
        />
      ))}
      {/* Axis spokes */}
      {AXES.map((_, i) => {
        const [x, y] = getXY(i, RADIUS)
        return (
          <line
            key={i}
            x1={CENTER} y1={CENTER} x2={x} y2={y}
            stroke="rgba(255,255,255,0.07)"
            strokeWidth="0.5"
          />
        )
      })}
      {/* Data area */}
      <polygon
        points={dataPolygon}
        fill="rgba(251,146,60,0.18)"
        stroke="rgba(251,146,60,0.75)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {/* Data dots */}
      {AXES.map(({ key }, i) => {
        const [x, y] = getXY(i, (clamp(score[key]) / 100) * RADIUS)
        return <circle key={i} cx={x} cy={y} r="2.5" fill="rgba(251,146,60,0.95)" />
      })}
      {/* Labels */}
      {AXES.map(({ label }, i) => {
        const [lx, ly] = getXY(i, RADIUS + 15)
        return (
          <text
            key={i}
            x={lx.toFixed(1)}
            y={ly.toFixed(1)}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize="7"
            fill="rgba(161,161,170,0.85)"
          >
            {label}
          </text>
        )
      })}
    </svg>
  )
}

// ── Panel ─────────────────────────────────────────────────────────────────────

interface ConfidenceScorePanelProps {
  isOpen: boolean
  onClose: () => void
  score: ConfidenceScoreResponse | null
  loading: boolean
  onRefresh: () => void
}

function scoreColor(v: number) {
  return v >= 80 ? 'text-emerald-400' : v >= 60 ? 'text-amber-400' : 'text-rose-400'
}


export default function ConfidenceScorePanel({
  isOpen,
  onClose,
  score,
  loading,
  onRefresh,
}: ConfidenceScorePanelProps) {
  if (!isOpen) return null

  return (
    <div
      className="fixed inset-y-0 right-0 z-50 flex w-[340px] flex-col border-l border-white/[0.07] bg-[#0c0c10] shadow-2xl"
      role="dialog"
      aria-label="Resume Quality Score"
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-white/[0.06] px-4 py-3">
        <div>
          <p className="text-xs font-semibold text-zinc-200">Quality Score</p>
          <p className="text-[10px] text-zinc-500">Rule-based resume quality analysis</p>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-zinc-500 transition hover:bg-white/10 hover:text-zinc-200"
          aria-label="Close panel"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading && !score ? (
          <div className="flex items-center justify-center gap-2 py-12 text-xs text-zinc-500">
            <span className="h-4 w-4 animate-spin rounded-full border border-zinc-600 border-t-zinc-300" />
            Analyzing resume quality…
          </div>
        ) : !score ? (
          <div className="flex flex-col items-center gap-3 py-12">
            <p className="text-xs text-zinc-500">No score yet</p>
            <button
              onClick={onRefresh}
              className="rounded-md bg-white/[0.05] px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-white/10"
            >
              Score Now
            </button>
          </div>
        ) : (
          <>
            {/* Score badge + radar */}
            <div className="flex items-center gap-4">
              {/* Circular badge */}
              <div className="relative shrink-0">
                <svg width="76" height="76" viewBox="0 0 36 36" aria-hidden>
                  <circle
                    cx="18" cy="18" r="15.9"
                    fill="none"
                    stroke="rgba(255,255,255,0.06)"
                    strokeWidth="2.5"
                  />
                  <circle
                    cx="18" cy="18" r="15.9"
                    fill="none"
                    stroke={score.overall >= 80 ? '#34d399' : score.overall >= 60 ? '#f59e0b' : '#f87171'}
                    strokeWidth="2.5"
                    strokeDasharray={`${score.overall} ${100 - score.overall}`}
                    strokeLinecap="round"
                    transform="rotate(-90 18 18)"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className={`text-xl font-bold tabular-nums leading-none ${scoreColor(score.overall)}`}>
                    {score.overall}
                  </span>
                  <span className={`text-xs font-bold ${scoreColor(score.overall)}`}>
                    {score.grade}
                  </span>
                </div>
              </div>

              {/* Radar chart */}
              <RadarChart score={score} />
            </div>

            {/* Dimension bars */}
            <div className="mt-4 space-y-2">
              {AXES.map(({ key, label }) => {
                const val = clamp(score[key])
                return (
                  <div key={key} className="flex items-center gap-2 text-[11px]">
                    <span className="w-16 shrink-0 text-zinc-500">{label}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-white/[0.06]">
                      <div
                        className={`h-full rounded-full transition-all ${
                          val >= 80 ? 'bg-emerald-400' : val >= 60 ? 'bg-amber-400' : 'bg-rose-400'
                        }`}
                        style={{ width: `${val}%` }}
                      />
                    </div>
                    <span className={`w-6 tabular-nums text-right ${scoreColor(val)}`}>{val}</span>
                  </div>
                )
              })}
            </div>

            {/* Improvements */}
            {score.improvements.length > 0 && (
              <div className="mt-5 space-y-1.5">
                <p className="text-[10px] uppercase tracking-widest text-zinc-600">Suggestions</p>
                {score.improvements.map((imp, i) => (
                  <div
                    key={i}
                    className="flex gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-[11px] text-zinc-300"
                  >
                    <span className="mt-px shrink-0 text-orange-400/70">→</span>
                    <span>{imp}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Refresh */}
            <button
              onClick={onRefresh}
              disabled={loading}
              className="mt-4 flex items-center gap-1.5 self-start rounded-md border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-[11px] text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-200 disabled:opacity-40"
            >
              {loading && (
                <span className="h-2.5 w-2.5 animate-spin rounded-full border border-zinc-500 border-t-zinc-200" />
              )}
              Refresh Score
            </button>
          </>
        )}
      </div>
    </div>
  )
}
