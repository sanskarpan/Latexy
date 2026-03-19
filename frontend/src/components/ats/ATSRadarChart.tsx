'use client'

interface RadarDimension {
  key: string
  label: string
}

const DIMENSIONS: RadarDimension[] = [
  { key: 'grammar',               label: 'Grammar'   },
  { key: 'bullet_clarity',        label: 'Bullets'   },
  { key: 'section_completeness',  label: 'Sections'  },
  { key: 'page_density',          label: 'Density'   },
  { key: 'keyword_density',       label: 'Keywords'  },
]

interface ATSRadarChartProps {
  scores: Record<string, number>
}

export default function ATSRadarChart({ scores }: ATSRadarChartProps) {
  const cx = 120
  const cy = 110
  const maxR = 80
  const n = DIMENSIONS.length

  const point = (i: number, r: number) => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
  }

  const polyPath = (r: number) => {
    const pts = Array.from({ length: n }, (_, i) => point(i, r))
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') + ' Z'
  }

  const dataPath = () => {
    const pts = DIMENSIONS.map((dim, i) => {
      const score = scores[dim.key] ?? 0
      return point(i, (score / 100) * maxR)
    })
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') + ' Z'
  }

  return (
    <svg viewBox="0 0 240 220" width="100%" style={{ maxWidth: 240 }}>
      {/* Background rings */}
      {[0.25, 0.5, 0.75, 1.0].map((frac) => (
        <path
          key={frac}
          d={polyPath(maxR * frac)}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="1"
        />
      ))}

      {/* Axis spokes */}
      {DIMENSIONS.map((_, i) => {
        const p = point(i, maxR)
        return (
          <line
            key={i}
            x1={cx} y1={cy}
            x2={p.x.toFixed(1)} y2={p.y.toFixed(1)}
            stroke="rgba(255,255,255,0.08)"
            strokeWidth="1"
          />
        )
      })}

      {/* Filled data polygon */}
      <path d={dataPath()} fill="rgba(139,92,246,0.15)" stroke="#8b5cf6" strokeWidth="1.5" />

      {/* Data point dots */}
      {DIMENSIONS.map((dim, i) => {
        const score = scores[dim.key] ?? 0
        const p = point(i, (score / 100) * maxR)
        return <circle key={i} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r="3" fill="#8b5cf6" />
      })}

      {/* Axis labels + scores */}
      {DIMENSIONS.map((dim, i) => {
        const lp = point(i, maxR + 24)
        const score = scores[dim.key] ?? 0
        const color = score >= 80 ? '#34d399' : score >= 60 ? '#f59e0b' : '#f87171'
        return (
          <g key={i}>
            <text x={lp.x.toFixed(1)} y={(lp.y - 5).toFixed(1)} textAnchor="middle" fill="rgba(255,255,255,0.65)" fontSize="9" fontWeight="600">
              {dim.label}
            </text>
            <text x={lp.x.toFixed(1)} y={(lp.y + 7).toFixed(1)} textAnchor="middle" fill={color} fontSize="8">
              {Math.round(score)}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
