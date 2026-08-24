'use client'

import { useState } from 'react'
import { Group } from '@visx/group'
import { scaleBand, scaleLinear, scaleTime } from '@visx/scale'
import { AreaClosed, Bar, LinePath, Pie } from '@visx/shape'
import { GridRows } from '@visx/grid'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { curveMonotoneX } from '@visx/curve'

export interface ActivityPoint {
  date: string
  value: number
}

export interface FeaturePoint {
  name: string
  value: number
}

export interface StatusPoint {
  name: string
  value: number
}

const chartMargin = { top: 16, right: 16, bottom: 36, left: 46 }

export function ActivityAreaChart({ data, width = 760, height = 280 }: { data: ActivityPoint[]; width?: number; height?: number }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  if (data.length === 0) {
    return <EmptyChart label="No activity data available yet." />
  }

  const parsed = data
    .map((point) => ({
      date: new Date(point.date),
      value: point.value,
    }))
    .filter((point) => !Number.isNaN(point.date.getTime()))

  if (parsed.length === 0) {
    return <EmptyChart label="No activity data available yet." />
  }

  const xMax = width - chartMargin.left - chartMargin.right
  const yMax = height - chartMargin.top - chartMargin.bottom
  const minDate = parsed[0].date
  const maxDate = parsed[parsed.length - 1].date
  const maxValue = Math.max(...parsed.map((point) => point.value), 1)

  const xScale = scaleTime<number>({
    range: [0, xMax],
    domain: [minDate, maxDate],
  })

  const yScale = scaleLinear<number>({
    range: [yMax, 0],
    domain: [0, maxValue * 1.15],
    nice: true,
  })

  const peakPoint = parsed.reduce((best, point) => (point.value > best.value ? point : best), parsed[0])
  const peakLabel = `${peakPoint.date.getMonth() + 1}/${peakPoint.date.getDate()}`
  const totalActivity = parsed.reduce((sum, point) => sum + point.value, 0)
  const activityLabel = `Daily activity over ${parsed.length} ${parsed.length === 1 ? 'day' : 'days'}: ${totalActivity} total, peak ${peakPoint.value} on ${peakLabel}.`

  return (
    <>
      <table className="sr-only">
        <caption>{activityLabel}</caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Activity</th>
          </tr>
        </thead>
        <tbody>
          {parsed.map((point) => (
            <tr key={point.date.toISOString()}>
              <td>{`${point.date.getMonth() + 1}/${point.date.getDate()}`}</td>
              <td>{point.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[280px] w-full" role="img" aria-label={activityLabel}>
      <Group left={chartMargin.left} top={chartMargin.top}>
        <GridRows
          scale={yScale}
          width={xMax}
          height={yMax}
          stroke="var(--line)"
          strokeDasharray="2,3"
          pointerEvents="none"
        />

        <AreaClosed
          data={parsed}
          x={(point) => xScale(point.date) ?? 0}
          y={(point) => yScale(point.value) ?? 0}
          yScale={yScale}
          curve={curveMonotoneX}
          fill="url(#activityAreaGradient)"
          stroke="var(--accent)"
          strokeWidth={2.2}
        />

        <LinePath
          data={parsed}
          x={(point) => xScale(point.date) ?? 0}
          y={(point) => yScale(point.value) ?? 0}
          curve={curveMonotoneX}
          stroke="var(--fg-3)"
          strokeWidth={1}
        />

        <AxisLeft
          scale={yScale}
          numTicks={4}
          tickStroke="var(--line)"
          stroke="var(--line-2)"
          tickLabelProps={() => ({ fill: 'var(--fg-3)', fontSize: 10, textAnchor: 'end', dx: -4, dy: 3 })}
        />

        <AxisBottom
          top={yMax}
          scale={xScale}
          numTicks={5}
          tickFormat={(value) => {
            const dt = value as Date
            return `${dt.getMonth() + 1}/${dt.getDate()}`
          }}
          tickStroke="var(--line)"
          stroke="var(--line-2)"
          tickLabelProps={() => ({ fill: 'var(--fg-3)', fontSize: 10, textAnchor: 'middle', dy: 12 })}
        />

        {/* Hover read-out: guide line, point marker, and a value tooltip. */}
        {hoverIdx != null && parsed[hoverIdx] && (() => {
          const p = parsed[hoverIdx]
          const cx = xScale(p.date) ?? 0
          const cy = yScale(p.value) ?? 0
          const label = `${p.date.getMonth() + 1}/${p.date.getDate()}`
          const boxW = 96
          const boxH = 34
          const bx = Math.min(Math.max(cx - boxW / 2, 0), Math.max(0, xMax - boxW))
          const by = Math.max(cy - boxH - 10, 0)
          return (
            <g pointerEvents="none">
              <line x1={cx} y1={0} x2={cx} y2={yMax} stroke="var(--line-2)" strokeDasharray="3,3" />
              <circle cx={cx} cy={cy} r={4} fill="var(--accent)" stroke="var(--bg)" strokeWidth={2} />
              <rect x={bx} y={by} width={boxW} height={boxH} rx={6} fill="var(--surface)" stroke="var(--line)" />
              <text x={bx + 9} y={by + 14} fontSize={10} fill="var(--fg-3)">{label}</text>
              <text x={bx + 9} y={by + 27} fontSize={12} fontWeight={600} fill="var(--fg)">
                {p.value} {p.value === 1 ? 'action' : 'actions'}
              </text>
            </g>
          )
        })()}

        {/* Transparent overlay captures the pointer to drive the tooltip. */}
        <rect
          x={0}
          y={0}
          width={xMax}
          height={yMax}
          fill="transparent"
          style={{ cursor: 'crosshair' }}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            if (rect.width === 0) return
            const localX = ((e.clientX - rect.left) / rect.width) * xMax
            let best = 0
            let bestDist = Infinity
            parsed.forEach((pt, i) => {
              const d = Math.abs((xScale(pt.date) ?? 0) - localX)
              if (d < bestDist) { bestDist = d; best = i }
            })
            setHoverIdx(best)
          }}
          onMouseLeave={() => setHoverIdx(null)}
        />
      </Group>

      <defs>
        <linearGradient id="activityAreaGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.56} />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.02} />
        </linearGradient>
      </defs>
      </svg>
    </>
  )
}

export function FeatureUsageBars({ data, width = 760, height = 260 }: { data: FeaturePoint[]; width?: number; height?: number }) {
  if (data.length === 0) {
    return <EmptyChart label="No feature usage tracked yet." />
  }

  const normalized = data
    .slice(0, 8)
    .map((item) => ({ ...item, name: item.name.replace(/_/g, ' ') }))
    .sort((a, b) => b.value - a.value)

  // Category names live in a dedicated left gutter (outside the bar track) so
  // they never collide with the value labels, which sit at the end of each
  // bar — inside it when there's room, otherwise just outside so short bars
  // stay legible instead of overlapping the name.
  const nameGutter = 116
  const xMax = width - chartMargin.left - chartMargin.right - nameGutter
  const yMax = height - chartMargin.top - chartMargin.bottom

  const xScale = scaleLinear<number>({
    range: [0, xMax],
    domain: [0, Math.max(...normalized.map((item) => item.value), 1) * 1.1],
  })

  const yScale = scaleBand<string>({
    range: [0, yMax],
    domain: normalized.map((item) => item.name),
    padding: 0.28,
  })

  const topFeature = normalized[0]
  const featureLabel = `Feature usage across ${normalized.length} ${normalized.length === 1 ? 'feature' : 'features'}: ${normalized
    .map((item) => `${item.name} ${item.value}`)
    .join(', ')}. Most used: ${topFeature.name} with ${topFeature.value}.`

  return (
    <>
      <table className="sr-only">
        <caption>{featureLabel}</caption>
        <thead>
          <tr>
            <th scope="col">Feature</th>
            <th scope="col">Uses</th>
          </tr>
        </thead>
        <tbody>
          {normalized.map((item) => (
            <tr key={item.name}>
              <td>{item.name}</td>
              <td>{item.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[260px] w-full" role="img" aria-label={featureLabel}>
      <Group left={chartMargin.left} top={chartMargin.top}>
        {normalized.map((item) => {
          const y = yScale(item.name)
          if (y === undefined) return null
          const rowCenter = y + yScale.bandwidth() / 2 + 4
          return (
            <text key={`name-${item.name}`} x={nameGutter - 10} y={rowCenter} textAnchor="end" fill="var(--fg-2)" fontSize={10}>
              {item.name}
            </text>
          )
        })}
      </Group>

      <Group left={chartMargin.left + nameGutter} top={chartMargin.top}>
        <GridRows scale={yScale} width={xMax} height={yMax} stroke="var(--line)" pointerEvents="none" />

        {normalized.map((item, index) => {
          const y = yScale(item.name)
          const barWidth = xScale(item.value)
          if (y === undefined) return null

          const alpha = 0.36 + (normalized.length - index) * 0.06
          const rowCenter = y + yScale.bandwidth() / 2 + 4
          // A value label needs ~22px to sit legibly inside the bar; shorter
          // bars push the label just outside the bar's end instead, so it
          // never overlaps the bar (or the now separately-anchored name).
          const valueFitsInside = barWidth >= 28
          return (
            <Group key={item.name}>
              <Bar
                x={0}
                y={y}
                width={barWidth}
                height={yScale.bandwidth()}
                rx={8}
                fill="var(--accent)"
                fillOpacity={Math.min(alpha, 0.9)}
              />
              <text
                x={valueFitsInside ? barWidth - 6 : barWidth + 6}
                y={rowCenter}
                textAnchor={valueFitsInside ? 'end' : 'start'}
                fill={valueFitsInside ? 'var(--accent-fg)' : 'var(--fg)'}
                fontSize={10}
                fontWeight={700}
              >
                {item.value}
              </text>
            </Group>
          )
        })}
      </Group>
      </svg>
    </>
  )
}

export function StatusDonutChart({
  data,
  width = 280,
  height = 280,
  totalLabel = 'RUNS',
}: {
  data: StatusPoint[]
  width?: number
  height?: number
  /** Small caption under the center total (e.g. "RUNS" vs "LAST 10") so the
   *  donut is honest about its scope when it's driven by a fallback sample
   *  rather than the full range-scoped distribution. */
  totalLabel?: string
}) {
  if (data.length === 0) {
    return <EmptyChart label="No run statuses to display." />
  }

  const filtered = data.filter((item) => item.value > 0)
  const total = filtered.reduce((sum, item) => sum + item.value, 0)

  if (filtered.length === 0 || total === 0) {
    return <EmptyChart label="No run statuses to display." />
  }

  const colors: Record<string, string> = {
    completed: 'var(--ok)',
    processing: 'var(--accent)',
    queued: 'var(--warn)',
    failed: 'var(--err)',
    cancelled: 'var(--fg-3)',
  }

  const radius = Math.min(width, height) / 2

  const donutLabel = `${totalLabel === 'RUNS' ? 'Run statuses' : `Run statuses (${totalLabel.toLowerCase()})`}, ${total} total: ${filtered
    .map((item) => `${item.name} ${item.value} (${Math.round((item.value / total) * 100)}%)`)
    .join(', ')}.`

  return (
    <div className="flex items-center gap-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[220px] w-[220px]" role="img" aria-label={donutLabel}>
        <Group top={height / 2} left={width / 2}>
          <Pie<StatusPoint>
            data={filtered}
            pieValue={(item) => item.value}
            outerRadius={radius - 10}
            innerRadius={radius - 44}
            padAngle={0.02}
          >
            {(pie) =>
              pie.arcs.map((arc) => (
                <g key={arc.data.name}>
                  <path d={pie.path(arc) || undefined} fill={colors[arc.data.name] || 'var(--accent)'} />
                </g>
              ))
            }
          </Pie>
          <text textAnchor="middle" fill="var(--fg)" fontSize={24} fontWeight={700} dy={-4}>
            {total}
          </text>
          <text textAnchor="middle" fill="var(--fg-3)" fontSize={10} dy={14}>
            {totalLabel}
          </text>
        </Group>
      </svg>

      <div className="space-y-2 text-xs">
        {filtered.map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colors[item.name] || 'var(--accent)' }} />
              <span className="uppercase tracking-[0.12em] text-fg-2">{item.name}</span>
            </div>
            <span className="font-semibold text-fg">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-[240px] items-center justify-center rounded-[var(--radius-md)] border border-dashed border-line text-sm text-fg-3">
      {label}
    </div>
  )
}
