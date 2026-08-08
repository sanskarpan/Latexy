/**
 * Workbench (#1095) — the Miller-columns view: drill down through your work,
 * with the machine's activity docked at the bottom. Opt-in view (`/workbench`),
 * non-destructive to the conversational transcript. Owns navigation state +
 * keyboard handling; delegates rendering to MillerColumns and JobDock.
 */
import React, { useEffect, useRef, useState } from 'react'
import { Box, Text, useInput } from 'ink'
import { useStore } from '@nanostores/react'
import { theme } from '../../lib/theme.js'
import { COLLECTIONS, fetchCollectionCounts, fetchDockJobs, fetchResumes } from '../../lib/workbench-data.js'
import {
  $workbench,
  closeWorkbench,
  drillIn,
  drillOut,
  filteredResumes,
  moveCursor,
  setData,
  setFilter,
} from '../../stores/workbench.js'
import { MillerColumns } from './MillerColumns.js'
import { JobDock } from './JobDock.js'
import { truncate } from './bits.js'

export function Workbench(): React.ReactElement {
  const s = useStore($workbench)
  const [filtering, setFiltering] = useState(false)
  // Generation counter guards the poll timer against StrictMode double-mount
  // (the #1095 spec's "double-speed spinner" trap).
  const gen = useRef(0)

  useEffect(() => {
    gen.current += 1
    const mine = gen.current
    let timer: ReturnType<typeof setInterval> | null = null

    const load = async (): Promise<void> => {
      setData({ loading: true })
      const [resumes, counts, jobs] = await Promise.all([fetchResumes(), fetchCollectionCounts(), fetchDockJobs()])
      if (gen.current !== mine) return
      setData({ resumes, counts, jobs, loading: false })
    }
    void load()
    timer = setInterval(() => {
      if (gen.current !== mine) return
      void fetchDockJobs().then((jobs) => {
        if (gen.current === mine) setData({ jobs })
      })
    }, 3000)

    return () => {
      if (timer != null) clearInterval(timer)
    }
  }, [])

  useInput((input, key) => {
    if (filtering) {
      if (key.escape || key.return) {
        setFiltering(false)
        return
      }
      if (key.backspace || key.delete) {
        setFilter(s.filter.slice(0, -1))
        return
      }
      if (input && !key.ctrl && !key.meta) setFilter(s.filter + input)
      return
    }
    if (key.escape || input === 'q') {
      closeWorkbench()
      return
    }
    if (input === 'h' || key.leftArrow) return drillOut()
    if (input === 'l' || key.rightArrow || key.return) return drillIn()
    if (input === 'j' || key.downArrow) return moveCursor(1)
    if (input === 'k' || key.upArrow) return moveCursor(-1)
    if (input === '/') {
      setFiltering(true)
      return
    }
  })

  const items = s.collectionKey === 'resumes' ? filteredResumes(s) : []
  const collection = COLLECTIONS[s.cursor[0]]?.label ?? 'workspace'
  const selected = items[s.cursor[1]]
  const crumb = ['⬡ latexy', collection, selected ? truncate(selected.title, 24) : '']
    .filter(Boolean)
    .join('  ▸  ')

  return (
    <Box flexDirection="column" height="100%">
      {/* breadcrumb — the breadcrumb IS the state */}
      <Box justifyContent="space-between" paddingX={1}>
        <Text>
          <Text color={theme.brand} bold>
            {crumb}
          </Text>
        </Text>
        <Text dimColor>{filtering ? 'filter — esc to exit' : 'q quit  ^k palette'}</Text>
      </Box>

      <Box flexGrow={1} overflow="hidden">
        <MillerColumns
          focused={s.focused}
          counts={s.counts}
          cursor={s.cursor}
          resumes={items}
          filter={s.filter}
          loading={s.loading}
        />
      </Box>

      <JobDock jobs={s.jobs} />

      <Box paddingX={1}>
        <Text dimColor>h/l column   j/k move   ⏎ drill in   / filter   q quit</Text>
      </Box>
    </Box>
  )
}
