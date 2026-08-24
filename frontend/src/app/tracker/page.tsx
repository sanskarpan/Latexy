'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Link from 'next/link'
import { Plus, MoreHorizontal, ExternalLink, Trash2, Pencil, X, StickyNote, Search } from 'lucide-react'
import { toast } from 'sonner'
import {
  DndContext,
  DragEndEvent,
  DragOverEvent,
  DragOverlay,
  DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { apiClient, type JobApplication, type TrackerStats } from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import AddApplicationModal from '@/components/AddApplicationModal'
import LoadingSpinner from '@/components/LoadingSpinner'

// ------------------------------------------------------------------ //
//  Column config                                                       //
// ------------------------------------------------------------------ //

const COLUMNS = [
  { id: 'applied', label: 'Applied', color: 'border-t-accent/60', badge: 'bg-accent-soft text-accent-strong' },
  { id: 'phone_screen', label: 'Phone Screen', color: 'border-t-accent/60', badge: 'bg-accent-soft text-accent-strong' },
  { id: 'technical', label: 'Technical', color: 'border-t-warn/60', badge: 'bg-warn/10 text-warn' },
  { id: 'onsite', label: 'On-Site', color: 'border-t-accent/60', badge: 'bg-accent-soft text-accent-strong' },
  { id: 'offer', label: 'Offer', color: 'border-t-ok/60', badge: 'bg-ok/10 text-ok' },
  { id: 'rejected', label: 'Rejected', color: 'border-t-err/60', badge: 'bg-err/10 text-err' },
  { id: 'withdrawn', label: 'Withdrawn', color: 'border-t-line-2', badge: 'bg-surface-2 text-fg-3' },
] as const

const STATUSES = [
  { value: 'applied', label: 'Applied' },
  { value: 'phone_screen', label: 'Phone Screen' },
  { value: 'technical', label: 'Technical' },
  { value: 'onsite', label: 'On-Site' },
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'withdrawn', label: 'Withdrawn' },
]

function atsColor(score: number) {
  if (score >= 75) return 'bg-ok/10 text-ok ring-ok/20'
  if (score >= 55) return 'bg-warn/10 text-warn ring-warn/20'
  return 'bg-err/10 text-err ring-err/20'
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const days = Math.floor(diff / 86400000)
  if (days === 0) return 'today'
  if (days === 1) return '1 day ago'
  if (days < 30) return `${days} days ago`
  const months = Math.floor(days / 30)
  return months === 1 ? '1 month ago' : `${months} months ago`
}

// ------------------------------------------------------------------ //
//  Logo / avatar helper                                                //
// ------------------------------------------------------------------ //

// `logoUrl` (server-constructed logo.clearbit.com lookup) is accepted for
// backward compatibility but intentionally unused — the Clearbit Logo API
// domain no longer resolves, so attempting it fired a failed network
// request (and a console error) on every card render. We render a text
// avatar instead of ever attempting the external fetch.
function CompanyAvatar({ name }: { name: string; logoUrl?: string | null }) {
  const initials = name
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')

  return (
    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-surface-2 text-[11px] font-bold text-fg-2">
      {initials || '?'}
    </div>
  )
}

// ------------------------------------------------------------------ //
//  Draggable card                                                      //
// ------------------------------------------------------------------ //

interface ApplicationCardProps {
  app: JobApplication
  onDelete: (id: string) => void
  onEdit: (app: JobApplication) => void
  onStatusChange: (id: string, status: string) => void
  isDragging?: boolean
}

function ApplicationCard({ app, onDelete, onEdit, onStatusChange, isDragging = false }: ApplicationCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging: sortableDragging } =
    useSortable({ id: app.id })
  const [menuOpen, setMenuOpen] = useState(false)
  const [notesOpen, setNotesOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  const menuTriggerRef = useRef<HTMLButtonElement>(null)
  const firstMenuItemRef = useRef<HTMLButtonElement>(null)
  const [menuPos, setMenuPos] = useState<{ top?: number; bottom?: number; right: number } | null>(null)

  useEffect(() => { setMounted(true) }, [])

  const closeMenu = useCallback((restoreFocus: boolean) => {
    setMenuOpen(false)
    if (restoreFocus) menuTriggerRef.current?.focus()
  }, [])

  // Escape closes the menu and returns focus to its trigger; focus moves into
  // the menu (first item) as soon as it opens, so it behaves like a real menu.
  useEffect(() => {
    if (!menuOpen) return
    firstMenuItemRef.current?.focus()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        closeMenu(true)
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [menuOpen, closeMenu])

  function openMenu() {
    if (menuTriggerRef.current) {
      const rect = menuTriggerRef.current.getBoundingClientRect()
      const margin = 8
      const menuHeight = 88 // approx height of 2-item menu
      const right = Math.max(margin, window.innerWidth - rect.right)
      const spaceBelow = window.innerHeight - rect.bottom - margin
      // Flip upward when there isn't enough room below the trigger.
      if (spaceBelow < menuHeight) {
        setMenuPos({ bottom: window.innerHeight - rect.top + 4, right })
      } else {
        setMenuPos({ top: rect.bottom + 4, right })
      }
    }
    setMenuOpen(true)
  }

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: sortableDragging ? 0.4 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`group relative rounded-[var(--radius-lg)] border border-line bg-surface p-3.5 shadow-sm transition hover:border-line-2 ${
        isDragging ? 'shadow-[var(--shadow-2)] ring-1 ring-accent/20' : ''
      }`}
    >
      {/* Drag handle area */}
      <div {...attributes} {...listeners} className="cursor-grab active:cursor-grabbing">
        <div className="flex items-start gap-2.5">
          <CompanyAvatar name={app.company_name} logoUrl={app.company_logo_url} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-fg leading-tight">{app.company_name}</p>
            <p className="truncate text-xs text-fg-2 mt-0.5">{app.role_title}</p>
          </div>
        </div>
      </div>

      {/* Meta row */}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {app.ats_score_at_submission != null && (
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold tabular-nums ring-1 ${atsColor(app.ats_score_at_submission)}`}>
            ATS {Math.round(app.ats_score_at_submission)}
          </span>
        )}
        <span className="text-[10px] text-fg-3">{timeAgo(app.applied_at)}</span>
        <div className="ml-auto flex items-center gap-1.5">
          {app.notes && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setNotesOpen((v) => !v) }}
              aria-expanded={notesOpen}
              aria-label={notesOpen ? 'Hide notes' : 'Show notes'}
              title="Notes"
              className={`transition ${notesOpen ? 'text-accent-strong' : 'text-fg-3 hover:text-fg-2'}`}
            >
              <StickyNote size={11} />
            </button>
          )}
          {app.job_url && (
            <a
              href={app.job_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              aria-label="Open job posting"
              className="text-fg-3 transition hover:text-fg-2"
            >
              <ExternalLink size={11} />
            </a>
          )}
        </div>
      </div>

      {/* Notes preview (read-only detail) */}
      {app.notes && notesOpen && (
        <p className="mt-2 max-h-28 overflow-y-auto whitespace-pre-wrap rounded-[var(--radius-md)] bg-surface-2 p-2 text-[11px] leading-relaxed text-fg-2">
          {app.notes}
        </p>
      )}

      {/* Non-drag status control — keyboard & touch accessible alternative to dragging */}
      <div className="mt-2.5">
        <label className="sr-only" htmlFor={`status-${app.id}`}>
          Move {app.company_name} to status
        </label>
        <select
          id={`status-${app.id}`}
          value={app.status}
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          onChange={(e) => { e.stopPropagation(); onStatusChange(app.id, e.target.value) }}
          className="w-full cursor-pointer rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-1 text-[11px] text-fg-2 outline-none transition focus:border-accent"
        >
          {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </div>

      {/* Overflow menu — always visible on touch/coarse pointers and on keyboard focus */}
      <div className="absolute right-2 top-2 opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100">
        <button
          ref={menuTriggerRef}
          type="button"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={(e) => { e.stopPropagation(); menuOpen ? closeMenu(false) : openMenu() }}
          className="rounded p-1 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
        >
          <MoreHorizontal size={14} />
        </button>
        {/* Rendered via portal to document.body with fixed positioning so the
            menu escapes the column's overflow-y-auto and the board's
            overflow-x-auto clipping. */}
        {mounted && menuOpen && menuPos && createPortal(
          <>
            <button
              type="button"
              className="fixed inset-0 z-[200]"
              onClick={() => closeMenu(false)}
              aria-label="Close menu"
              tabIndex={-1}
            />
            <div
              role="menu"
              aria-label={`Actions for ${app.company_name}`}
              className="z-[201] w-36 rounded-[var(--radius-lg)] border border-line bg-surface p-1 shadow-[var(--shadow-2)]"
              style={{
                position: 'fixed',
                top: menuPos.top,
                bottom: menuPos.bottom,
                right: menuPos.right,
              }}
            >
              <button
                ref={firstMenuItemRef}
                type="button"
                role="menuitem"
                onClick={() => { closeMenu(true); onEdit(app) }}
                className="flex w-full items-center gap-2 rounded-[var(--radius-md)] px-3 py-1.5 text-xs text-fg-2 transition hover:bg-surface-2"
              >
                <Pencil size={12} /> Edit
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => { closeMenu(true); onDelete(app.id) }}
                className="flex w-full items-center gap-2 rounded-[var(--radius-md)] px-3 py-1.5 text-xs text-err transition hover:bg-err/10"
              >
                <Trash2 size={12} /> Delete
              </button>
            </div>
          </>,
          document.body
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ //
//  Droppable column                                                    //
// ------------------------------------------------------------------ //

interface ColumnProps {
  columnId: string
  label: string
  colorClass: string
  badgeClass: string
  apps: JobApplication[]
  onDelete: (id: string) => void
  onEdit: (app: JobApplication) => void
  onStatusChange: (id: string, status: string) => void
}

function KanbanColumn({ columnId, label, colorClass, badgeClass, apps, onDelete, onEdit, onStatusChange }: ColumnProps) {
  // The column container itself (not just its cards) must be a registered
  // droppable target — otherwise an empty column has no children for dnd-kit
  // to hit-test against and drops onto it silently fail.
  const { setNodeRef, isOver } = useDroppable({ id: columnId })
  return (
    <div className={`flex min-h-[200px] w-[80vw] max-w-[300px] flex-shrink-0 flex-col rounded-[var(--radius-lg)] border border-line bg-bg border-t-2 sm:w-[260px] ${colorClass}`}>
      <div className="flex items-center gap-2 px-3.5 py-3">
        <span className="text-xs font-semibold text-fg-2">{label}</span>
        <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold ${badgeClass}`}>
          {apps.length}
        </span>
      </div>
      <div
        ref={setNodeRef}
        className={`flex flex-1 flex-col gap-2 overflow-y-auto px-2.5 pb-3 rounded-[var(--radius-md)] transition-colors ${
          isOver ? 'bg-accent-soft/40' : ''
        }`}
      >
        <SortableContext items={apps.map((a) => a.id)} strategy={verticalListSortingStrategy}>
          {apps.map((app) => (
            <ApplicationCard key={app.id} app={app} onDelete={onDelete} onEdit={onEdit} onStatusChange={onStatusChange} />
          ))}
        </SortableContext>
        {apps.length === 0 && (
          <div className="flex h-16 items-center justify-center rounded-[var(--radius-md)] border border-dashed border-line text-[11px] text-fg-3">
            Drop here
          </div>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ //
//  Local stats recomputation                                          //
// ------------------------------------------------------------------ //

// Mirrors the aggregation done by GET /tracker/stats (see
// backend/app/api/tracker_routes.py::get_tracker_stats) so the stats strip
// can be recomputed optimistically from boardData the instant it changes,
// instead of only reflecting reality after a round trip to the server.
function computeStatsFromBoard(board: Record<string, JobApplication[]>): TrackerStats {
  const apps = Object.values(board).flat()
  const total = apps.length
  const byStatus: Record<string, number> = Object.fromEntries(COLUMNS.map((c) => [c.id, 0]))
  const atsScores: number[] = []

  const now = Date.now()
  const weekStart = now - 7 * 86400000
  const monthStart = new Date()
  monthStart.setUTCDate(1)
  monthStart.setUTCHours(0, 0, 0, 0)
  const monthStartMs = monthStart.getTime()

  let thisWeek = 0
  let thisMonth = 0

  for (const a of apps) {
    if (a.status in byStatus) byStatus[a.status] += 1
    if (a.ats_score_at_submission != null) atsScores.push(a.ats_score_at_submission)
    const appliedMs = new Date(a.applied_at).getTime()
    if (!Number.isNaN(appliedMs)) {
      if (appliedMs >= weekStart) thisWeek += 1
      if (appliedMs >= monthStartMs) thisMonth += 1
    }
  }

  const progressed = ['phone_screen', 'technical', 'onsite', 'offer'].reduce(
    (sum, s) => sum + (byStatus[s] ?? 0),
    0
  )

  return {
    total_applications: total,
    by_status: byStatus,
    avg_ats_score: atsScores.length
      ? Math.round((atsScores.reduce((a, b) => a + b, 0) / atsScores.length) * 10) / 10
      : null,
    applications_this_week: thisWeek,
    applications_this_month: thisMonth,
    response_rate: total > 0 ? Math.round((progressed / total) * 10000) / 10000 : 0,
    offer_rate: total > 0 ? Math.round((byStatus.offer / total) * 10000) / 10000 : 0,
  }
}

// ------------------------------------------------------------------ //
//  Stats bar                                                           //
// ------------------------------------------------------------------ //

function StatsBar({ stats }: { stats: TrackerStats | null }) {
  if (!stats || stats.total_applications === 0) return null
  return (
    <div className="flex flex-wrap gap-4 rounded-[var(--radius-lg)] border border-line bg-bg px-5 py-3 text-xs">
      <span className="text-fg-2">
        <span className="font-semibold text-fg">{stats.total_applications}</span> total
      </span>
      <span className="text-fg-2">
        Response rate:{' '}
        <span className="font-semibold text-fg">{Math.round(stats.response_rate * 100)}%</span>
      </span>
      <span className="text-fg-2">
        Offer rate:{' '}
        <span className="font-semibold text-fg">{Math.round(stats.offer_rate * 100)}%</span>
      </span>
      {stats.avg_ats_score != null && (
        <span className="text-fg-2">
          Avg ATS: <span className="font-semibold text-fg">{Math.round(stats.avg_ats_score)}</span>
        </span>
      )}
      <span className="text-fg-2">
        This week:{' '}
        <span className="font-semibold text-fg">{stats.applications_this_week}</span>
      </span>
    </div>
  )
}

// ------------------------------------------------------------------ //
//  Main page                                                           //
// ------------------------------------------------------------------ //

export default function TrackerPage() {
  const { session, isPending: sessionLoading } = useRequireAuth()

  const [boardData, setBoardData] = useState<Record<string, JobApplication[]>>(() =>
    Object.fromEntries(COLUMNS.map((c) => [c.id, []]))
  )
  const [stats, setStats] = useState<TrackerStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [editingApp, setEditingApp] = useState<JobApplication | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [dragSourceCol, setDragSourceCol] = useState<string | null>(null)

  // Client-side filter / sort controls
  const [searchQuery, setSearchQuery] = useState('')
  const [onlyThisWeek, setOnlyThisWeek] = useState(false)
  const [atsMin, setAtsMin] = useState(0)
  const [sortBy, setSortBy] = useState<'recent' | 'ats' | 'company' | 'manual'>('recent')
  // Per-column manual card order (app ids), persisted in the browser. The board
  // has no backend position field, so a manual reorder is remembered locally and
  // shown when the Sort control is set to "Manual" (dragging within a column
  // switches into it) — no more silent snap-back on drop.
  const [manualOrder, setManualOrder] = useState<Record<string, string[]>>({})
  useEffect(() => {
    try { setManualOrder(JSON.parse(localStorage.getItem('latexy_tracker_order') || '{}')) } catch { /* ignore */ }
  }, [])
  const persistManualOrder = useCallback((next: Record<string, string[]>) => {
    setManualOrder(next)
    try { localStorage.setItem('latexy_tracker_order', JSON.stringify(next)) } catch { /* ignore */ }
  }, [])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )


  const loadBoard = useCallback(async () => {
    if (!session) return
    try {
      const [listResp, statsResp] = await Promise.all([
        apiClient.listApplications(),
        apiClient.getTrackerStats(),
      ])
      setBoardData(listResp.by_status as Record<string, JobApplication[]>)
      setStats(statsResp)
    } catch {
      toast.error('Failed to load tracker')
    } finally {
      setIsLoading(false)
    }
  }, [session])

  useEffect(() => {
    loadBoard()
  }, [loadBoard])

  // Find which column an app lives in
  const findColumn = useCallback(
    (appId: string): string | null => {
      for (const [colId, apps] of Object.entries(boardData)) {
        if (apps.some((a) => a.id === appId)) return colId
      }
      return null
    },
    [boardData]
  )

  // Find app by id across all columns
  const findApp = useCallback(
    (appId: string): JobApplication | undefined => {
      for (const apps of Object.values(boardData)) {
        const a = apps.find((x) => x.id === appId)
        if (a) return a
      }
    },
    [boardData]
  )

  const handleDragStart = (event: DragStartEvent) => {
    const id = event.active.id as string
    setActiveId(id)
    setDragSourceCol(findColumn(id))
  }

  const handleDragOver = (event: DragOverEvent) => {
    const { active, over } = event
    if (!over) return

    const activeId = active.id as string
    const overId = over.id as string

    const activeCol = findColumn(activeId)
    // over.id is either a column id or an app id — resolve to column
    const overCol = COLUMNS.find((c) => c.id === overId)?.id ?? findColumn(overId)

    if (!activeCol || !overCol || activeCol === overCol) return

    setBoardData((prev) => {
      const app = prev[activeCol].find((a) => a.id === activeId)
      if (!app) return prev
      return {
        ...prev,
        [activeCol]: prev[activeCol].filter((a) => a.id !== activeId),
        [overCol]: [...prev[overCol], { ...app, status: overCol }],
      }
    })
  }

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    const sourceCol = dragSourceCol
    setActiveId(null)
    setDragSourceCol(null)
    if (!over) return

    const activeId = active.id as string
    const overId = over.id as string

    const finalCol = COLUMNS.find((c) => c.id === overId)?.id ?? findColumn(overId)
    if (!finalCol) return

    if (!sourceCol) return

    // Within-column drop → reorder and remember it. The board has no backend
    // position field, so the order is persisted in the browser and the Sort
    // control switches to "Manual" so it actually displays (no silent snap-back).
    if (sourceCol === finalCol) {
      const displayed = filteredBoard[finalCol] ?? []
      const oldIndex = displayed.findIndex((a) => a.id === activeId)
      if (oldIndex === -1) return
      let newIndex = displayed.findIndex((a) => a.id === overId)
      if (newIndex === -1) newIndex = displayed.length - 1 // dropped on the column body → end
      if (oldIndex !== newIndex) {
        const reordered = arrayMove(displayed, oldIndex, newIndex)
        persistManualOrder({ ...manualOrder, [finalCol]: reordered.map((a) => a.id) })
      }
      if (sortBy !== 'manual') setSortBy('manual')
      return
    }

    try {
      await apiClient.updateApplicationStatus(activeId, finalCol)
      setStats(await apiClient.getTrackerStats())
    } catch {
      toast.error('Failed to move card — reverting')
      loadBoard()
    }
  }

  // Non-drag status change (from the card <select>) — keyboard / touch accessible
  const handleStatusChange = useCallback(async (id: string, newStatus: string) => {
    const sourceCol = findColumn(id)
    if (!sourceCol || sourceCol === newStatus) return
    const app = boardData[sourceCol]?.find((a) => a.id === id)
    if (!app) return
    setBoardData((prev) => ({
      ...prev,
      [sourceCol]: prev[sourceCol].filter((a) => a.id !== id),
      [newStatus]: [{ ...app, status: newStatus }, ...(prev[newStatus] ?? [])],
    }))
    try {
      await apiClient.updateApplicationStatus(id, newStatus)
      setStats(await apiClient.getTrackerStats())
    } catch {
      toast.error('Failed to move card — reverting')
      loadBoard()
    }
  }, [boardData, findColumn, loadBoard])

  const handleDelete = useCallback((id: string) => {
    const col = findColumn(id)
    if (!col) return
    const index = boardData[col].findIndex((a) => a.id === id)
    const app = boardData[col][index]
    if (!app) return

    // Optimistic remove — the real API call is deferred so an "Undo" can cancel it.
    // Stats are recomputed locally in lockstep with the board so the stats strip
    // reflects the deletion immediately, rather than lagging behind the deferred
    // network delete + refetch below (or requiring a manual reload to catch up).
    const boardAfterDelete = { ...boardData, [col]: boardData[col].filter((a) => a.id !== id) }
    setBoardData(boardAfterDelete)
    setStats(computeStatsFromBoard(boardAfterDelete))

    let undone = false
    const timer = setTimeout(async () => {
      if (undone) return
      try {
        await apiClient.deleteApplication(id)
        setStats(await apiClient.getTrackerStats())
      } catch {
        toast.error('Failed to delete — restoring')
        loadBoard()
      }
    }, 5000)

    toast('Application deleted', {
      duration: 5000,
      action: {
        label: 'Undo',
        onClick: () => {
          undone = true
          clearTimeout(timer)
          // Reinsert at the original position within its column.
          setBoardData((prev) => {
            const next = [...(prev[col] ?? [])]
            next.splice(Math.min(index, next.length), 0, app)
            const restored = { ...prev, [col]: next }
            setStats(computeStatsFromBoard(restored))
            return restored
          })
        },
      },
    })
  }, [boardData, findColumn, loadBoard])

  const handleAppCreated = useCallback((app: JobApplication) => {
    setBoardData((prev) => ({
      ...prev,
      [app.status]: [app, ...(prev[app.status] ?? [])],
    }))
    apiClient.getTrackerStats().then(setStats).catch(() => {})
  }, [])

  const activeApp = activeId ? findApp(activeId) : null

  const filtersActive = searchQuery.trim() !== '' || onlyThisWeek || atsMin > 0

  // Client-side view over boardData: search + filters + sort. Cross-column drag and
  // status changes still mutate boardData directly, so this only affects presentation.
  const totalApps = useMemo(
    () => Object.values(boardData).reduce((sum, apps) => sum + apps.length, 0),
    [boardData],
  )

  const filteredBoard = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    const weekAgo = Date.now() - 7 * 86400000
    const out: Record<string, JobApplication[]> = {}
    for (const col of COLUMNS) {
      let apps = (boardData[col.id] ?? []).filter((a) => {
        if (q && !`${a.company_name} ${a.role_title}`.toLowerCase().includes(q)) return false
        if (onlyThisWeek && new Date(a.applied_at).getTime() < weekAgo) return false
        if (atsMin > 0 && (a.ats_score_at_submission == null || a.ats_score_at_submission < atsMin)) return false
        return true
      })
      if (sortBy === 'ats') {
        apps = [...apps].sort((a, b) => (b.ats_score_at_submission ?? -1) - (a.ats_score_at_submission ?? -1))
      } else if (sortBy === 'company') {
        apps = [...apps].sort((a, b) => a.company_name.localeCompare(b.company_name))
      } else if (sortBy === 'manual') {
        const order = manualOrder[col.id] ?? []
        const rank = (id: string) => { const i = order.indexOf(id); return i === -1 ? Number.MAX_SAFE_INTEGER : i }
        apps = [...apps].sort((a, b) => (rank(a.id) - rank(b.id)) || (new Date(b.applied_at).getTime() - new Date(a.applied_at).getTime()))
      } else {
        apps = [...apps].sort((a, b) => new Date(b.applied_at).getTime() - new Date(a.applied_at).getTime())
      }
      out[col.id] = apps
    }
    return out
  }, [boardData, searchQuery, onlyThisWeek, atsMin, sortBy, manualOrder])

  if (sessionLoading || (isLoading && session)) {
    return (
      <div className="flex h-[70vh] items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (!session) return null

  return (
    <div className="content-shell space-y-5">
      {/* Header */}
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Tracker</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">Job Applications</h1>
          <p className="mt-1 text-sm text-fg-2">
            Track every application across its full lifecycle.
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/workspace" className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2">
            Workspace
          </Link>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 flex items-center gap-1.5"
          >
            <Plus size={13} />
            Add Application
          </button>
        </div>
      </section>

      {/* Stats */}
      <StatsBar stats={stats} />

      {totalApps === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-[var(--radius-lg)] border border-dashed border-line bg-bg px-6 py-16 text-center">
          <div className="grid h-12 w-12 place-items-center rounded-[var(--radius-pill)] bg-accent-soft text-accent-strong">
            <Plus size={20} />
          </div>
          <h2 className="text-lg font-semibold text-fg">No applications yet</h2>
          <p className="max-w-sm text-sm text-fg-2">
            Track every job application from first submission to offer — add one to see your pipeline take shape across the columns below.
          </p>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="mt-2 flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110"
          >
            <Plus size={13} />
            Add your first application
          </button>
        </div>
      ) : (
      <>
      {/* Filters / search / sort */}
      <section className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3" />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search company or role…"
            aria-label="Search applications by company or role"
            className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 py-1.5 pl-8 text-xs text-fg outline-none transition placeholder:text-fg-3 focus:border-accent"
          />
        </div>

        <button
          type="button"
          onClick={() => setOnlyThisWeek((v) => !v)}
          aria-pressed={onlyThisWeek}
          className={`rounded-[var(--radius-md)] border px-3 py-1.5 text-xs transition ${
            onlyThisWeek
              ? 'border-accent bg-accent-soft text-accent-strong'
              : 'border-line text-fg-2 hover:bg-surface-2'
          }`}
        >
          This week
        </button>

        <label className="sr-only" htmlFor="ats-filter">Minimum ATS score</label>
        <select
          id="ats-filter"
          value={atsMin}
          onChange={(e) => setAtsMin(Number(e.target.value))}
          className="rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs text-fg-2 outline-none transition focus:border-accent"
        >
          <option value={0}>Any ATS</option>
          <option value={55}>ATS 55+</option>
          <option value={75}>ATS 75+</option>
        </select>

        <label className="sr-only" htmlFor="sort-by">Sort applications</label>
        <select
          id="sort-by"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as 'recent' | 'ats' | 'company' | 'manual')}
          className="rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs text-fg-2 outline-none transition focus:border-accent"
        >
          <option value="recent">Sort: Recent</option>
          <option value="ats">Sort: ATS</option>
          <option value="company">Sort: Company</option>
          <option value="manual">Sort: Manual</option>
        </select>

        {filtersActive && (
          <button
            type="button"
            onClick={() => { setSearchQuery(''); setOnlyThisWeek(false); setAtsMin(0) }}
            className="rounded-[var(--radius-md)] px-2.5 py-1.5 text-xs text-fg-3 transition hover:text-fg"
          >
            Clear
          </button>
        )}
      </section>

      {/* Kanban board — horizontally scrollable, contained to viewport width */}
      <div className="max-w-full overflow-x-auto pb-4">
        <DndContext
          sensors={sensors}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDragEnd={handleDragEnd}
        >
          <div className="flex gap-3" style={{ minWidth: 'max-content' }}>
            {COLUMNS.map((col) => (
              <KanbanColumn
                key={col.id}
                columnId={col.id}
                label={col.label}
                colorClass={col.color}
                badgeClass={col.badge}
                apps={filteredBoard[col.id] ?? []}
                onDelete={handleDelete}
                onEdit={setEditingApp}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>

          <DragOverlay>
            {activeApp && (
              <div className="w-[260px] rounded-[var(--radius-lg)] border border-accent/20 bg-surface p-3.5 shadow-[var(--shadow-2)] ring-1 ring-accent/20">
                <div className="flex items-start gap-2.5">
                  <CompanyAvatar name={activeApp.company_name} logoUrl={activeApp.company_logo_url} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-fg">{activeApp.company_name}</p>
                    <p className="truncate text-xs text-fg-2">{activeApp.role_title}</p>
                  </div>
                </div>
              </div>
            )}
          </DragOverlay>
        </DndContext>
      </div>
      </>
      )}

      {/* Add modal */}
      {showAddModal && (
        <AddApplicationModal
          onClose={() => setShowAddModal(false)}
          onCreated={handleAppCreated}
        />
      )}

      {/* Edit modal (reuses Add modal pre-filled) */}
      {editingApp && (
        <EditApplicationModal
          app={editingApp}
          onClose={() => setEditingApp(null)}
          onUpdated={(updated) => {
            setEditingApp(null)
            setBoardData((prev) => {
              const newBoard = { ...prev }
              // Remove from old column
              for (const col of COLUMNS) {
                newBoard[col.id] = newBoard[col.id].filter((a) => a.id !== updated.id)
              }
              // Add to new column
              newBoard[updated.status] = [updated, ...(newBoard[updated.status] ?? [])]
              return newBoard
            })
            apiClient.getTrackerStats().then(setStats).catch(() => {})
          }}
        />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ //
//  Inline edit modal                                                   //
// ------------------------------------------------------------------ //

function EditApplicationModal({
  app,
  onClose,
  onUpdated,
}: {
  app: JobApplication
  onClose: () => void
  onUpdated: (updated: JobApplication) => void
}) {
  const [companyName, setCompanyName] = useState(app.company_name)
  const [roleTitle, setRoleTitle] = useState(app.role_title)
  const [status, setStatus] = useState(app.status)
  const [jobUrl, setJobUrl] = useState(app.job_url ?? '')
  const [notes, setNotes] = useState(app.notes ?? '')
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsSubmitting(true)
    try {
      const updated = await apiClient.updateApplication(app.id, {
        company_name: companyName.trim(),
        role_title: roleTitle.trim(),
        status,
        job_url: jobUrl.trim() || undefined,
        notes: notes.trim() || undefined,
      })
      toast.success('Application updated')
      onUpdated(updated)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="text-sm font-semibold text-fg">Edit Application</h2>
          <button type="button" onClick={onClose} className="rounded-[var(--radius-md)] p-1.5 text-fg-3 hover:text-fg">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">Company</label>
              <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} required
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent" />
            </div>
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">Role</label>
              <input value={roleTitle} onChange={(e) => setRoleTitle(e.target.value)} required
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent" />
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">Status</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent">
              {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">Job URL</label>
            <input type="url" value={jobUrl} onChange={(e) => setJobUrl(e.target.value)} placeholder="https://..."
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent" />
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">Notes</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
              className="w-full resize-none rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent" />
          </div>
          <div className="flex justify-end gap-2 border-t border-line pt-4">
            <button type="button" onClick={onClose}
              className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 hover:text-fg">
              Cancel
            </button>
            <button type="submit" disabled={isSubmitting}
              className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50">
              {isSubmitting ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
