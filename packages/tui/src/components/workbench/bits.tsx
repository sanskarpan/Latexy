/**
 * Workbench visual primitives (#1095). Small, pure, presentational.
 */
import React from 'react'
import { Text } from 'ink'
import { theme } from '../../lib/theme.js'

/** Focus rail glyph — constant width so nothing reflows when focus moves. */
export function railGlyph(focused: boolean): string {
  return focused ? '┃' : '┊'
}

/** Map an ATS letter grade to a theme colour. */
export function gradeColor(grade?: string | null): string {
  if (!grade) return theme.muted
  const g = grade[0]?.toUpperCase()
  if (g === 'A') return theme.success
  if (g === 'B') return theme.brand
  if (g === 'C') return theme.warning
  return theme.error
}

/** Colour for a positional cell in a 0..9 heat ramp (red → amber → green). */
function heatColor(cell: number): string {
  if (cell <= 1) return theme.error
  if (cell <= 4) return theme.warning
  return theme.success
}

/**
 * Positional gradient bar for a 0..100 score — fixed 10 slots where each slot
 * keeps its ramp colour, so a long bar passes through red → amber → green.
 */
export function ScoreBar({ score, width = 10 }: { score: number; width?: number }): React.ReactElement {
  const filled = Math.round((Math.max(0, Math.min(100, score)) / 100) * width)
  const cells = Array.from({ length: width }, (_, i) => i)
  return (
    <Text>
      {cells.map((i) => (
        <Text key={i} color={i < filled ? heatColor(Math.floor((i / width) * 10)) : theme.muted}>
          {i < filled ? '█' : '░'}
        </Text>
      ))}
    </Text>
  )
}

const SPARK = '▁▂▃▄▅▆▇█'
/** Unicode sparkline from a series of numbers, scaled to the series range. */
export function sparkline(values: number[]): string {
  if (values.length === 0) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return values
    .map((v) => SPARK[Math.min(SPARK.length - 1, Math.floor(((v - min) / span) * (SPARK.length - 1)))])
    .join('')
}

/** Width-safe truncate with an ellipsis (uses code-point length; good enough for latin/mono). */
export function truncate(s: string, width: number): string {
  const chars = [...s]
  if (chars.length <= width) return s
  if (width <= 1) return '…'
  return chars.slice(0, width - 1).join('') + '…'
}

/** Compact relative-time label ("2h", "3d", "2w") from an ISO timestamp. */
export function relTime(iso?: string): string {
  if (!iso) return ''
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ''
  const secs = Math.max(0, (Date.now() - then) / 1000)
  if (secs < 3600) return `${Math.floor(secs / 60)}m`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h`
  if (secs < 604800) return `${Math.floor(secs / 86400)}d`
  return `${Math.floor(secs / 604800)}w`
}
