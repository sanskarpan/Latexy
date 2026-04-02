'use client'

import { useEffect, useState } from 'react'
import { Group } from '@visx/group'
import { scaleLinear, scaleTime } from '@visx/scale'
import { LinePath } from '@visx/shape'
import { GridRows } from '@visx/grid'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { curveMonotoneX } from '@visx/curve'
import { apiClient, type ScoreHistoryPoint } from '@/lib/api-client'

interface ScoreHistoryChartProps {
  resumeId: string
}

const W = 400
const H = 160
const margin = { top: 12, right: 12, bottom: 32, left: 36 }
const xMax = W - margin.left - margin.right
const yMax = H - margin.top - margin.bottom

function scoreColor(score: number) {
  return score >= 80 ? '#34d399' : score >= 60 ? '#f59e0b' : '#f87171'
}

export default function ScoreHistoryChart({ resumeId }: ScoreHistoryChartProps) {
  const [points, setPoints] = useState<ScoreHistoryPoint[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    apiClient.getScoreHistory(resumeId).then((data) => {
      if (!cancelled) setPoints(data)
    }).catch(() => {/* silent — panel just won't show data */}).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [resumeId])

  if (loading) {
    return <div className="h-10 animate-pulse rounded-lg bg-white/[0.03]" />
  }

  if (points.length === 0) {
    return (
      <p className="text-[11px] text-zinc-600">
        No score history yet — optimize this resume to track progress.
      </p>
    )
  }

  if (points.length === 1) {
    const score = points[0].ats_score
    return (
      <div className="flex items-center gap-3">
        <span className="text-2xl font-bold tabular-nums" style={{ color: scoreColor(score) }}>
          {Math.round(score)}
        </span>
        <p className="text-[11px] text-zinc-500">Optimize more to see progress over time.</p>
      </div>
    )
  }

  const parsed = points.map((p) => ({ date: new Date(p.timestamp), score: p.ats_score }))
  const first = parsed[0].score
  const last = parsed[parsed.length - 1].score
  const delta = Math.round(last - first)

  const xScale = scaleTime<number>({
    range: [0, xMax],
    domain: [parsed[0].date, parsed[parsed.length - 1].date],
  })
  const yScale = scaleLinear<number>({
    range: [yMax, 0],
    domain: [Math.max(0, Math.min(...parsed.map((p) => p.score)) - 10), 100],
    nice: true,
  })

  const latestColor = scoreColor(last)

  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-bold tabular-nums" style={{ color: latestColor }}>
          {Math.round(last)}
        </span>
        {delta !== 0 && (
          <span className={`text-[11px] font-semibold ${delta > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {delta > 0 ? '↑' : '↓'} {Math.abs(delta)} pts since first optimization
          </span>
        )}
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: H }}>
        <defs>
          <linearGradient id="scoreLineGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={scoreColor(first)} stopOpacity={0.6} />
            <stop offset="100%" stopColor={latestColor} />
          </linearGradient>
        </defs>
        <Group left={margin.left} top={margin.top}>
          <GridRows
            scale={yScale}
            width={xMax}
            height={yMax}
            stroke="rgba(255,255,255,0.05)"
            strokeDasharray="2,3"
            pointerEvents="none"
          />
          <LinePath
            data={parsed}
            x={(d) => xScale(d.date) ?? 0}
            y={(d) => yScale(d.score) ?? 0}
            curve={curveMonotoneX}
            stroke="url(#scoreLineGrad)"
            strokeWidth={2}
          />
          {/* Dot on latest point */}
          <circle
            cx={xScale(parsed[parsed.length - 1].date)}
            cy={yScale(parsed[parsed.length - 1].score)}
            r={4}
            fill={latestColor}
          />
          <AxisBottom
            scale={xScale}
            top={yMax}
            numTicks={Math.min(parsed.length, 4)}
            tickFormat={(d) => {
              const date = d as Date
              return `${date.getMonth() + 1}/${date.getDate()}`
            }}
            stroke="rgba(255,255,255,0.08)"
            tickStroke="rgba(255,255,255,0.08)"
            tickLabelProps={() => ({
              fill: 'rgba(255,255,255,0.3)',
              fontSize: 9,
              textAnchor: 'middle',
            })}
          />
          <AxisLeft
            scale={yScale}
            numTicks={4}
            stroke="rgba(255,255,255,0.08)"
            tickStroke="rgba(255,255,255,0.08)"
            tickLabelProps={() => ({
              fill: 'rgba(255,255,255,0.3)',
              fontSize: 9,
              textAnchor: 'end',
              dy: '0.33em',
              dx: -4,
            })}
          />
        </Group>
      </svg>
    </div>
  )
}
