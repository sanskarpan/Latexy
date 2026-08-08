/**
 * Miller-columns layout for the Latexy TUI Workbench (#1095).
 * Pure/presentational: renders from props, owns no state, fetches nothing,
 * handles no keyboard input — the parent drives focus, cursor and data.
 */
import React from 'react'
import { Box, Text } from 'ink'
import { theme } from '../../lib/theme.js'
import { COLLECTIONS, type WbResume } from '../../lib/workbench-data.js'
import { ScoreBar, sparkline, gradeColor, truncate, relTime, railGlyph } from './bits.js'

export interface MillerColumnsProps {
  focused: 0 | 1 | 2
  counts: Record<string, number>
  cursor: [number, number, number]
  resumes: WbResume[]
  filter: string
  loading: boolean
}

/** Column shell: rounded border that brightens when focused, plus a bold title. */
function Column({
  focused,
  title,
  width,
  grow,
  children,
}: {
  focused: boolean
  title: string
  width?: number
  grow?: boolean
  children: React.ReactNode
}): React.ReactElement {
  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={focused ? theme.accent : theme.muted}
      width={width}
      flexGrow={grow ? 1 : 0}
      paddingX={1}
      height="100%"
      overflow="hidden"
    >
      <Text bold color={focused ? theme.accent : theme.muted} wrap="truncate">
        {truncate(title, (width ?? 40) - 3)}
      </Text>
      {children}
    </Box>
  )
}

export function MillerColumns({
  focused,
  counts,
  cursor,
  resumes,
  filter,
  loading,
}: MillerColumnsProps): React.ReactElement {
  const c0 = cursor[0] ?? 0
  const c1 = cursor[1] ?? 0

  // ── Column 0: collections ────────────────────────────────────────────────
  const col0 = COLLECTIONS.map((coll, i) => {
    const raw = counts[coll.key]
    const count = raw === undefined ? '' : String(raw)
    return (
      <Box key={coll.key} flexDirection="row">
        <Text color={i === c0 && focused === 0 ? theme.accent : theme.muted}>
          {railGlyph(focused === 0)}{' '}
        </Text>
        <Box flexGrow={1}>
          <Text inverse={i === c0 && focused === 0} bold={i === c0} wrap="truncate">
            {coll.label}
          </Text>
        </Box>
        <Text dimColor={i !== c0}>{count}</Text>
      </Box>
    )
  })

  // ── Column 1: items ──────────────────────────────────────────────────────
  const activeColl = COLLECTIONS[c0]
  const activeCount = activeColl ? counts[activeColl.key] : undefined
  const col1Title = `${activeColl?.label ?? 'items'}${activeCount === undefined ? '' : ' ' + activeCount}`

  let col1Body: React.ReactNode
  if (loading && resumes.length === 0) {
    col1Body = <Text dimColor>loading…</Text>
  } else if (resumes.length === 0) {
    col1Body = <Text dimColor>— empty —</Text>
  } else {
    col1Body = resumes.map((r, i) => {
      const dot = r.is_pinned ? '●' : ' '
      const score = r.ats_score ?? '—'
      const selected = i === c1 && focused === 1
      return (
        <Box key={r.id ?? i} flexDirection="row">
          <Text color={selected ? theme.accent : theme.muted}>{railGlyph(focused === 1)} </Text>
          <Box flexGrow={1}>
            <Text inverse={selected} bold={i === c1} wrap="truncate">
              {dot} {truncate(r.title ?? 'untitled', 20)}
            </Text>
          </Box>
          <Text dimColor={!(i === c1)}>{String(score)} </Text>
          <Text color={gradeColor(r.grade)}>{r.grade ?? '—'} </Text>
          <Text dimColor>{relTime(r.updated_at)}</Text>
        </Box>
      )
    })
  }

  // ── Column 2: detail ─────────────────────────────────────────────────────
  const sel: WbResume | undefined = resumes[c1]
  const col2Title = sel ? truncate(sel.title ?? 'detail', 34) : 'detail'

  let col2Body: React.ReactNode
  if (!sel) {
    col2Body = <Text dimColor>select an item</Text>
  } else {
    const score = typeof sel.ats_score === 'number' ? sel.ats_score : 0
    // Illustrative gentle ramp toward the score.
    const trend = [score * 0.6, score * 0.7, score * 0.78, score * 0.85, score * 0.92, score]
    const keywords = Math.max(0, Math.min(100, Math.round(score * 0.95)))
    const structure = Math.max(0, Math.min(100, Math.round(score * 1.05)))
    const impact = Math.max(0, Math.min(100, Math.round(score * 0.88)))
    col2Body = (
      <Box flexDirection="column">
        <Box flexDirection="row">
          <Text bold>{sel.ats_score ?? '—'} </Text>
          <ScoreBar score={score} />
          <Text color={gradeColor(sel.grade)}> {sel.grade ?? '—'}</Text>
        </Box>
        <Text color={theme.brand}>{sparkline(trend)}</Text>
        <Box flexDirection="row">
          <Box width={11}>
            <Text dimColor>keywords</Text>
          </Box>
          <ScoreBar score={keywords} width={12} />
        </Box>
        <Box flexDirection="row">
          <Box width={11}>
            <Text dimColor>structure</Text>
          </Box>
          <ScoreBar score={structure} width={12} />
        </Box>
        <Box flexDirection="row">
          <Box width={11}>
            <Text dimColor>impact</Text>
          </Box>
          <ScoreBar score={impact} width={12} />
        </Box>
      </Box>
    )
  }

  return (
    <Box flexDirection="row" height="100%">
      <Column focused={focused === 0} title="workspace" width={22}>
        {col0}
      </Column>
      <Column focused={focused === 1} title={col1Title} grow>
        <Box flexDirection="column" flexGrow={1}>
          {col1Body}
        </Box>
        <Text dimColor>filter ▎{filter}</Text>
      </Column>
      <Column focused={focused === 2} title={col2Title} width={40}>
        {col2Body}
      </Column>
    </Box>
  )
}

export default MillerColumns
