/**
 * Workbench navigation state (#1095) — Miller-columns model.
 *
 * Three columns: 0 = collections, 1 = items in the focused collection,
 * 2 = detail of the selected item. `focused` is which column has the cursor;
 * `cursor` holds the row index per column. The breadcrumb is derived from this
 * state (collection label ▸ selected item title).
 */
import { atom } from 'nanostores'
import { COLLECTIONS, type DockJob, type WbResume } from '../lib/workbench-data.js'

export interface WorkbenchState {
  active: boolean
  focused: 0 | 1 | 2
  cursor: [number, number, number]
  collectionKey: string
  resumes: WbResume[]
  counts: Record<string, number>
  jobs: DockJob[]
  filter: string
  loading: boolean
}

const initial: WorkbenchState = {
  active: false,
  focused: 0,
  cursor: [0, 0, 0],
  collectionKey: COLLECTIONS[0]!.key,
  resumes: [],
  counts: {},
  jobs: [],
  filter: '',
  loading: false,
}

export const $workbench = atom<WorkbenchState>(initial)

function set(patch: Partial<WorkbenchState>): void {
  $workbench.set({ ...$workbench.get(), ...patch })
}

export function openWorkbench(): void {
  set({ active: true })
}
export function closeWorkbench(): void {
  set({ active: false, filter: '' })
}

/** Items currently shown in column 1, honoring the inline filter. */
export function filteredResumes(s: WorkbenchState): WbResume[] {
  const f = s.filter.trim().toLowerCase()
  if (!f) return s.resumes
  return s.resumes.filter((r) => r.title.toLowerCase().includes(f))
}

export function moveCursor(delta: number): void {
  const s = $workbench.get()
  const col = s.focused
  const max =
    col === 0 ? COLLECTIONS.length - 1 : col === 1 ? Math.max(0, filteredResumes(s).length - 1) : 0
  const next = Math.min(max, Math.max(0, s.cursor[col] + delta))
  const cursor: [number, number, number] = [...s.cursor]
  cursor[col] = next
  // Moving in the collections column re-scopes the item column.
  if (col === 0) {
    cursor[1] = 0
    set({ cursor, collectionKey: COLLECTIONS[next]!.key })
  } else {
    set({ cursor })
  }
}

export function focusColumn(col: 0 | 1 | 2): void {
  set({ focused: col, filter: col === 0 ? '' : $workbench.get().filter })
}

/** `l` / Enter — drill one column to the right (0→1→2), clamped. */
export function drillIn(): void {
  const s = $workbench.get()
  if (s.focused < 2) focusColumn((s.focused + 1) as 0 | 1 | 2)
}
/** `h` — move one column left. */
export function drillOut(): void {
  const s = $workbench.get()
  if (s.focused > 0) focusColumn((s.focused - 1) as 0 | 1 | 2)
}

export function setFilter(f: string): void {
  const s = $workbench.get()
  const cursor: [number, number, number] = [...s.cursor]
  cursor[1] = 0
  set({ filter: f, cursor })
}

export function selectedResume(): WbResume | undefined {
  const s = $workbench.get()
  return filteredResumes(s)[s.cursor[1]]
}

export function setData(patch: Pick<Partial<WorkbenchState>, 'resumes' | 'counts' | 'jobs' | 'loading'>): void {
  set(patch)
}
