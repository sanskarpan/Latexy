import React from 'react'
import { describe, it, expect, beforeEach } from 'vitest'
import { render } from 'ink-testing-library'
import { MillerColumns } from '../components/workbench/MillerColumns.js'
import { JobDock } from '../components/workbench/JobDock.js'
import { ScoreBar, sparkline, gradeColor, truncate, relTime } from '../components/workbench/bits.js'
import {
  $workbench,
  openWorkbench,
  closeWorkbench,
  moveCursor,
  drillIn,
  drillOut,
  setFilter,
  filteredResumes,
} from '../stores/workbench.js'
import { COLLECTIONS, type WbResume } from '../lib/workbench-data.js'

const RESUMES: WbResume[] = [
  { id: '1', title: 'senior-swe-2026', ats_score: 84, grade: 'B+', updated_at: new Date(Date.now() - 7200_000).toISOString(), is_pinned: true },
  { id: '2', title: 'backend-generalist', ats_score: 79, grade: 'B', updated_at: new Date(Date.now() - 86400_000).toISOString() },
  { id: '3', title: 'ml-research', ats_score: 71, grade: 'C+', updated_at: new Date(Date.now() - 259200_000).toISOString() },
]

beforeEach(() => {
  $workbench.set({ active: false, focused: 0, cursor: [0, 0, 0], collectionKey: 'resumes', resumes: RESUMES, counts: { resumes: 3 }, jobs: [], filter: '', loading: false })
})

describe('workbench bits', () => {
  it('renders a positional score bar', () => {
    const { lastFrame } = render(<ScoreBar score={80} width={10} />)
    expect(lastFrame()).toMatch(/█/)
  })
  it('makes a sparkline scaled to the range', () => {
    expect(sparkline([1, 5, 9])).toHaveLength(3)
    expect(sparkline([])).toBe('')
  })
  it('maps grades to colours and truncates width-safely', () => {
    expect(gradeColor('A')).not.toBe(gradeColor('C'))
    expect(truncate('senior-software-engineer', 10)).toHaveLength(10)
  })
  it('formats relative time', () => {
    expect(relTime(new Date(Date.now() - 7200_000).toISOString())).toBe('2h')
  })
})

describe('workbench store — Miller-columns navigation', () => {
  it('opens and closes', () => {
    openWorkbench(); expect($workbench.get().active).toBe(true)
    closeWorkbench(); expect($workbench.get().active).toBe(false)
  })
  it('moves the cursor within a column and re-scopes on collection change', () => {
    moveCursor(1)
    expect($workbench.get().cursor[0]).toBe(1)
    expect($workbench.get().collectionKey).toBe(COLLECTIONS[1]!.key)
  })
  it('drills in and out across columns', () => {
    drillIn(); expect($workbench.get().focused).toBe(1)
    drillIn(); expect($workbench.get().focused).toBe(2)
    drillIn(); expect($workbench.get().focused).toBe(2) // clamped
    drillOut(); expect($workbench.get().focused).toBe(1)
  })
  it('filters the items column', () => {
    setFilter('ml')
    expect(filteredResumes($workbench.get()).map((r) => r.title)).toEqual(['ml-research'])
  })
})

describe('workbench components render', () => {
  it('MillerColumns shows collections and items', () => {
    const { lastFrame } = render(
      <MillerColumns focused={1} counts={{ resumes: 3 }} cursor={[0, 0, 0]} resumes={RESUMES} filter="" loading={false} />,
    )
    const out = lastFrame() ?? ''
    expect(out).toMatch(/resumes/)
    expect(out).toMatch(/senior-swe-2026/)
  })
  it('JobDock renders active jobs and an empty state', () => {
    const active = render(<JobDock jobs={[{ id: 'j1', kind: 'ats.deep', status: 'processing', percent: 62, label: 'senior-swe' }]} />)
    expect(active.lastFrame()).toMatch(/ats\.deep/)
    const empty = render(<JobDock jobs={[]} />)
    expect(empty.lastFrame()).toMatch(/no active jobs/i)
  })
})
