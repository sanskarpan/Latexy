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

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[280px] w-full">
      <Group left={chartMargin.left} top={chartMargin.top}>
        <GridRows
          scale={yScale}
          width={xMax}
          height={yMax}
          stroke="rgba(255,255,255,0.08)"
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
          stroke="rgba(251, 146, 60, 0.95)"
          strokeWidth={2.2}
        />

        <LinePath
          data={parsed}
          x={(point) => xScale(point.date) ?? 0}
          y={(point) => yScale(point.value) ?? 0}
          curve={curveMonotoneX}
          stroke="rgba(255, 222, 197, 0.9)"
          strokeWidth={1}
        />

        <AxisLeft
          scale={yScale}
          numTicks={4}
          tickStroke="rgba(255,255,255,0.18)"
          stroke="rgba(255,255,255,0.25)"
          tickLabelProps={() => ({ fill: 'rgba(161, 161, 170, 0.9)', fontSize: 10, textAnchor: 'end', dx: -4, dy: 3 })}
        />

        <AxisBottom
          top={yMax}
          scale={xScale}
          numTicks={5}
          tickFormat={(value) => {
            const dt = value as Date
            return `${dt.getMonth() + 1}/${dt.getDate()}`
          }}
          tickStroke="rgba(255,255,255,0.18)"
          stroke="rgba(255,255,255,0.25)"
          tickLabelProps={() => ({ fill: 'rgba(161, 161, 170, 0.9)', fontSize: 10, textAnchor: 'middle', dy: 12 })}
        />
      </Group>

      <defs>
        <linearGradient id="activityAreaGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(251,146,60,0.56)" />
          <stop offset="100%" stopColor="rgba(251,146,60,0.02)" />
        </linearGradient>
      </defs>
    </svg>
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

  const xMax = width - chartMargin.left - chartMargin.right
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

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[260px] w-full">
      <Group left={chartMargin.left} top={chartMargin.top}>
        <GridRows scale={yScale} width={xMax} height={yMax} stroke="rgba(255,255,255,0.05)" pointerEvents="none" />

        {normalized.map((item, index) => {
          const y = yScale(item.name)
          const barWidth = xScale(item.value)
          if (y === undefined) return null

          const alpha = 0.36 + (normalized.length - index) * 0.06
          return (
            <Group key={item.name}>
              <Bar
                x={0}
                y={y}
                width={barWidth}
                height={yScale.bandwidth()}
                rx={8}
                fill={`rgba(251, 146, 60, ${Math.min(alpha, 0.9)})`}
              />
              <text x={6} y={y + yScale.bandwidth() / 2 + 4} fill="rgba(255,255,255,0.9)" fontSize={10}>
                {item.name}
              </text>
              <text x={Math.max(barWidth - 6, 34)} y={y + yScale.bandwidth() / 2 + 4} textAnchor="end" fill="rgba(20,20,20,0.92)" fontSize={10} fontWeight={700}>
                {item.value}
              </text>
            </Group>
          )
        })}
      </Group>
    </svg>
  )
}

export function StatusDonutChart({ data, width = 280, height = 280 }: { data: StatusPoint[]; width?: number; height?: number }) {
  if (data.length === 0) {
    return <EmptyChart label="No run statuses to display." />
  }

  const filtered = data.filter((item) => item.value > 0)
  const total = filtered.reduce((sum, item) => sum + item.value, 0)

  if (filtered.length === 0 || total === 0) {
    return <EmptyChart label="No run statuses to display." />
  }

  const colors: Record<string, string> = {
    completed: 'rgba(16, 185, 129, 0.85)',
    processing: 'rgba(251, 146, 60, 0.9)',
    queued: 'rgba(245, 158, 11, 0.78)',
    failed: 'rgba(251, 113, 133, 0.82)',
    cancelled: 'rgba(161, 161, 170, 0.68)',
  }

  const radius = Math.min(width, height) / 2

  return (
    <div className="flex items-center gap-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[220px] w-[220px]">
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
                  <path d={pie.path(arc) || undefined} fill={colors[arc.data.name] || 'rgba(251,146,60,0.7)'} />
                </g>
              ))
            }
          </Pie>
          <text textAnchor="middle" fill="rgba(255,255,255,0.95)" fontSize={24} fontWeight={700} dy={-4}>
            {total}
          </text>
          <text textAnchor="middle" fill="rgba(161,161,170,0.95)" fontSize={10} dy={14}>
            RUNS
          </text>
        </Group>
      </svg>

      <div className="space-y-2 text-xs">
        {filtered.map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colors[item.name] || 'rgba(251,146,60,0.7)' }} />
              <span className="uppercase tracking-[0.12em] text-zinc-400">{item.name}</span>
            </div>
            <span className="font-semibold text-zinc-200">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-[240px] items-center justify-center rounded-xl border border-dashed border-white/10 text-sm text-zinc-500">
      {label}
    </div>
  )
}
