/**
 * Job dock (#1095) — always-on strip at the bottom of the Workbench showing
 * in-flight and recent jobs. Pure/stateless: takes props, renders. No data
 * fetching, no keyboard handling.
 */
import React from 'react'
import { Box, Text } from 'ink'
import { theme } from '../../lib/theme.js'
import { type DockJob } from '../../lib/workbench-data.js'
import { truncate } from './bits.js'

export interface JobDockProps {
  jobs: DockJob[]
}

const MAX_ROWS = 4
const BAR_WIDTH = 24

function statusGlyph(status: string): { glyph: string; color: string } {
  switch (status) {
    case 'processing':
    case 'queued':
      return { glyph: '◐', color: theme.brand }
    case 'completed':
      return { glyph: '✔', color: theme.success }
    case 'failed':
      return { glyph: '✖', color: theme.error }
    case 'cancelled':
      return { glyph: '⊘', color: theme.muted }
    default:
      return { glyph: '•', color: theme.muted }
  }
}

function statusLabel(status: string, percent: number): string {
  switch (status) {
    case 'processing':
    case 'queued':
      return `${percent}%`
    case 'completed':
      return 'done'
    case 'failed':
      return 'error'
    case 'cancelled':
      return 'cancelled'
    default:
      return `${percent}%`
  }
}

function ProgressBar({ percent, color }: { percent: number; color: string }): React.ReactElement {
  const safePercent = Math.max(0, Math.min(100, Number.isFinite(percent) ? percent : 0))
  const filled = Math.max(0, Math.min(BAR_WIDTH, Math.round((safePercent / 100) * BAR_WIDTH)))
  const empty = BAR_WIDTH - filled
  return (
    <Text>
      <Text color={color}>{'█'.repeat(filled)}</Text>
      <Text dimColor>{'░'.repeat(empty)}</Text>
    </Text>
  )
}

function JobRow({ job }: { job: DockJob }): React.ReactElement {
  const status = job?.status ?? 'unknown'
  const percent = Math.max(0, Math.min(100, Number(job?.percent ?? 0) || 0))
  const kind = truncate(job?.kind ?? 'job', 10).padEnd(10, ' ')
  const label = job?.label ?? (job?.id ? job.id.slice(0, 8) : '')
  const { glyph, color } = statusGlyph(status)

  return (
    <Box flexDirection="row" gap={1}>
      <Text color={color}>{glyph}</Text>
      <Text>{kind}</Text>
      <ProgressBar percent={percent} color={color} />
      <Text dimColor>{statusLabel(status, percent).padStart(5, ' ')}</Text>
      <Text dimColor wrap="truncate">
        {label}
      </Text>
    </Box>
  )
}

export function JobDock({ jobs }: JobDockProps): React.ReactElement {
  const safeJobs = Array.isArray(jobs) ? jobs.filter(Boolean) : []
  const activeCount = safeJobs.filter((j) => j?.status === 'processing' || j?.status === 'queued').length
  const visible = safeJobs.slice(0, MAX_ROWS)
  const overflow = safeJobs.length - visible.length

  return (
    <Box flexDirection="column" flexShrink={0} borderStyle="round" borderColor={theme.muted} paddingX={1}>
      <Box flexDirection="row" justifyContent="space-between">
        <Text bold color={theme.brand}>
          dock
        </Text>
        <Text dimColor>
          {safeJobs.length} jobs · {activeCount} active
        </Text>
      </Box>
      {safeJobs.length === 0 ? (
        <Text dimColor>— no active jobs —</Text>
      ) : (
        <>
          {visible.map((job, i) => (
            <JobRow key={job?.id || i} job={job} />
          ))}
          {overflow > 0 ? <Text dimColor>+{overflow} more</Text> : null}
        </>
      )}
    </Box>
  )
}

export default JobDock
