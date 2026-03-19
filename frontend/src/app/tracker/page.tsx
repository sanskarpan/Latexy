'use client'

import { useCallback, useEffect, useState } from 'react'
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
  { id: 'applied', label: 'Applied', color: 'border-t-blue-500/60', badge: 'bg-blue-500/10 text-blue-300' },
  { id: 'phone_screen', label: 'Phone Screen', color: 'border-t-violet-500/60', badge: 'bg-violet-500/10 text-violet-300' },
  { id: 'technical', label: 'Technical', color: 'border-t-amber-500/60', badge: 'bg-amber-500/10 text-amber-300' },
  { id: 'onsite', label: 'On-Site', color: 'border-t-orange-500/60', badge: 'bg-orange-500/10 text-orange-300' },
  { id: 'offer', label: 'Offer', color: 'border-t-emerald-500/60', badge: 'bg-emerald-500/10 text-emerald-300' },
  { id: 'rejected', label: 'Rejected', color: 'border-t-rose-500/60', badge: 'bg-rose-500/10 text-rose-300' },
  { id: 'withdrawn', label: 'Withdrawn', color: 'border-t-zinc-500/60', badge: 'bg-zinc-500/10 text-zinc-400' },
] as const

function atsColor(score: number) {
  if (score >= 75) return 'bg-emerald-500/10 text-emerald-300 ring-emerald-400/20'
  if (score >= 55) return 'bg-amber-500/10 text-amber-300 ring-amber-400/20'
  return 'bg-rose-500/10 text-rose-300 ring-rose-400/20'
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
        className="h-8 w-8 flex-shrink-0 rounded-lg object-contain bg-white/5 p-0.5"
      />
    )
  }
  return (
    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-zinc-800 text-[11px] font-bold text-zinc-300">
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

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: sortableDragging ? 0.4 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`group relative rounded-xl border border-white/10 bg-zinc-900 p-3.5 shadow-sm transition hover:border-white/20 ${
        isDragging ? 'shadow-2xl ring-1 ring-orange-300/20' : ''
      }`}
    >
      {/* Drag handle area */}
      <div {...attributes} {...listeners} className="cursor-grab active:cursor-grabbing">
        <div className="flex items-start gap-2.5">
          <CompanyAvatar name={app.company_name} logoUrl={app.company_logo_url} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-white leading-tight">{app.company_name}</p>
            <p className="truncate text-xs text-zinc-400 mt-0.5">{app.role_title}</p>
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
        <span className="text-[10px] text-zinc-600">{timeAgo(app.applied_at)}</span>
        {app.job_url && (
          <a
            href={app.job_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="ml-auto text-zinc-600 transition hover:text-zinc-300"
          >
            <ExternalLink size={11} />
          </a>
        )}
      </div>

      {/* Overflow menu */}
      <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v) }}
          className="rounded p-1 text-zinc-600 transition hover:bg-white/5 hover:text-zinc-300"
        >
          <MoreHorizontal size={14} />
        </button>
        {menuOpen && (
          <>
            <button
              type="button"
              className="fixed inset-0 z-10"
              onClick={() => setMenuOpen(false)}
              aria-label="Close menu"
              tabIndex={-1}
            />
            <div className="absolute right-0 top-6 z-20 w-36 rounded-xl border border-white/10 bg-zinc-900 p-1 shadow-xl">
              <button
                type="button"
                onClick={() => { setMenuOpen(false); onEdit(app) }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-white/5"
              >
                <Pencil size={12} /> Edit
              </button>
              <button
                type="button"
                onClick={() => { setMenuOpen(false); onDelete(app.id) }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-xs text-rose-400 transition hover:bg-rose-500/10"
              >
                <Trash2 size={12} /> Delete
              </button>
            </div>
          </>
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
    <div className={`flex min-h-[200px] w-[260px] flex-shrink-0 flex-col rounded-xl border border-white/10 bg-zinc-950 border-t-2 ${colorClass}`}>
      <div className="flex items-center gap-2 px-3.5 py-3">
        <span className="text-xs font-semibold text-zinc-300">{label}</span>
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
          <div className="flex h-16 items-center justify-center rounded-lg border border-dashed border-white/10 text-[11px] text-zinc-700">
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
    <div className="flex flex-wrap gap-4 rounded-xl border border-white/10 bg-zinc-950 px-5 py-3 text-xs">
      <span className="text-zinc-400">
        <span className="font-semibold text-white">{stats.total_applications}</span> total
      </span>
      <span className="text-zinc-400">
        Response rate:{' '}
        <span className="font-semibold text-white">{Math.round(stats.response_rate * 100)}%</span>
      </span>
      <span className="text-zinc-400">
        Offer rate:{' '}
        <span className="font-semibold text-white">{Math.round(stats.offer_rate * 100)}%</span>
      </span>
      {stats.avg_ats_score != null && (
        <span className="text-zinc-400">
          Avg ATS: <span className="font-semibold text-white">{Math.round(stats.avg_ats_score)}</span>
        </span>
      )}
      <span className="text-zinc-400">
        This week:{' '}
        <span className="font-semibold text-white">{stats.applications_this_week}</span>
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
          <p className="overline">Tracker</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Job Applications</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Track every application across its full lifecycle.
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/workspace" className="btn-ghost px-4 py-2 text-xs">
            Workspace
          </Link>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="btn-accent flex items-center gap-1.5 px-4 py-2 text-xs"
          >
            <Plus size={13} />
            Add Application
          </button>
        </div>
      </section>

      {/* Stats */}
      <StatsBar stats={stats} />

      {/* Kanban board */}
      <div className="overflow-x-auto pb-4">
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
              <div className="w-[260px] rounded-xl border border-orange-300/20 bg-zinc-900 p-3.5 shadow-2xl ring-1 ring-orange-300/20">
                <div className="flex items-start gap-2.5">
                  <CompanyAvatar name={activeApp.company_name} logoUrl={activeApp.company_logo_url} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">{activeApp.company_name}</p>
                    <p className="truncate text-xs text-zinc-400">{activeApp.role_title}</p>
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <h2 className="text-sm font-semibold text-white">Edit Application</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-zinc-500 hover:text-white">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Company</label>
              <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} required
                className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-orange-300/40" />
            </div>
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Role</label>
              <input value={roleTitle} onChange={(e) => setRoleTitle(e.target.value)} required
                className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-orange-300/40" />
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Status</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
              className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-orange-300/40">
              {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Job URL</label>
            <input type="url" value={jobUrl} onChange={(e) => setJobUrl(e.target.value)} placeholder="https://..."
              className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-orange-300/40" />
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Notes</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
              className="w-full resize-none rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-orange-300/40" />
          </div>
          <div className="flex justify-end gap-2 border-t border-white/10 pt-4">
            <button type="button" onClick={onClose}
              className="rounded-lg border border-white/10 px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white">
              Cancel
            </button>
            <button type="submit" disabled={isSubmitting}
              className="btn-accent px-4 py-2 text-xs disabled:opacity-50">
              {isSubmitting ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
