'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Plus, MoreHorizontal, ExternalLink, Trash2, Pencil, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  DndContext,
  DragEndEvent,
  DragOverEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { apiClient, type JobApplication, type TrackerStats } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
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

function CompanyAvatar({ name, logoUrl }: { name: string; logoUrl: string | null }) {
  const [imgFailed, setImgFailed] = useState(false)
  const initials = name
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')

  if (logoUrl && !imgFailed) {
    return (
      <img
        src={logoUrl}
        alt={name}
        onError={() => setImgFailed(true)}
        className="h-8 w-8 flex-shrink-0 rounded-[var(--radius-md)] object-contain bg-surface-2 p-0.5"
      />
    )
  }
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
  isDragging?: boolean
}

function ApplicationCard({ app, onDelete, onEdit, isDragging = false }: ApplicationCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging: sortableDragging } =
    useSortable({ id: app.id })
  const [menuOpen, setMenuOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  const menuTriggerRef = useRef<HTMLButtonElement>(null)
  const [menuPos, setMenuPos] = useState<{ top?: number; bottom?: number; right: number } | null>(null)

  useEffect(() => { setMounted(true) }, [])

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
        {app.job_url && (
          <a
            href={app.job_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="ml-auto text-fg-3 transition hover:text-fg-2"
          >
            <ExternalLink size={11} />
          </a>
        )}
      </div>

      {/* Overflow menu */}
      <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition">
        <button
          ref={menuTriggerRef}
          type="button"
          onClick={(e) => { e.stopPropagation(); menuOpen ? setMenuOpen(false) : openMenu() }}
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
              onClick={() => setMenuOpen(false)}
              aria-label="Close menu"
              tabIndex={-1}
            />
            <div
              className="z-[201] w-36 rounded-[var(--radius-lg)] border border-line bg-surface p-1 shadow-[var(--shadow-2)]"
              style={{
                position: 'fixed',
                top: menuPos.top,
                bottom: menuPos.bottom,
                right: menuPos.right,
              }}
            >
              <button
                type="button"
                onClick={() => { setMenuOpen(false); onEdit(app) }}
                className="flex w-full items-center gap-2 rounded-[var(--radius-md)] px-3 py-1.5 text-xs text-fg-2 transition hover:bg-surface-2"
              >
                <Pencil size={12} /> Edit
              </button>
              <button
                type="button"
                onClick={() => { setMenuOpen(false); onDelete(app.id) }}
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
}

function KanbanColumn({ columnId, label, colorClass, badgeClass, apps, onDelete, onEdit }: ColumnProps) {
  return (
    <div className={`flex min-h-[200px] w-[80vw] max-w-[300px] flex-shrink-0 flex-col rounded-[var(--radius-lg)] border border-line bg-bg border-t-2 sm:w-[260px] ${colorClass}`}>
      <div className="flex items-center gap-2 px-3.5 py-3">
        <span className="text-xs font-semibold text-fg-2">{label}</span>
        <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold ${badgeClass}`}>
          {apps.length}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto px-2.5 pb-3">
        <SortableContext items={apps.map((a) => a.id)} strategy={verticalListSortingStrategy}>
          {apps.map((app) => (
            <ApplicationCard key={app.id} app={app} onDelete={onDelete} onEdit={onEdit} />
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
  const { data: session, isPending: sessionLoading } = useSession()
  const router = useRouter()

  const [boardData, setBoardData] = useState<Record<string, JobApplication[]>>(() =>
    Object.fromEntries(COLUMNS.map((c) => [c.id, []]))
  )
  const [stats, setStats] = useState<TrackerStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [editingApp, setEditingApp] = useState<JobApplication | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [dragSourceCol, setDragSourceCol] = useState<string | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  useEffect(() => {
    if (!sessionLoading && !session) router.push('/login')
  }, [session, sessionLoading, router])

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

    // Compare against sourceCol captured at drag start — boardData is already optimistically updated
    if (!sourceCol || sourceCol === finalCol) return

    try {
      await apiClient.updateApplicationStatus(activeId, finalCol)
      setStats(await apiClient.getTrackerStats())
    } catch {
      toast.error('Failed to move card — reverting')
      loadBoard()
    }
  }

  const handleDelete = useCallback(async (id: string) => {
    const col = findColumn(id)
    if (!col) return
    // Optimistic remove
    setBoardData((prev) => ({
      ...prev,
      [col]: prev[col].filter((a) => a.id !== id),
    }))
    try {
      await apiClient.deleteApplication(id)
      toast.success('Application deleted')
      setStats(await apiClient.getTrackerStats())
    } catch {
      toast.error('Failed to delete')
      loadBoard()
    }
  }, [findColumn, loadBoard])

  const handleAppCreated = useCallback((app: JobApplication) => {
    setBoardData((prev) => ({
      ...prev,
      [app.status]: [app, ...(prev[app.status] ?? [])],
    }))
    apiClient.getTrackerStats().then(setStats).catch(() => {})
  }, [])

  const activeApp = activeId ? findApp(activeId) : null

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
                apps={boardData[col.id] ?? []}
                onDelete={handleDelete}
                onEdit={setEditingApp}
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

const STATUSES = [
  { value: 'applied', label: 'Applied' },
  { value: 'phone_screen', label: 'Phone Screen' },
  { value: 'technical', label: 'Technical' },
  { value: 'onsite', label: 'On-Site' },
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'withdrawn', label: 'Withdrawn' },
]

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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
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
