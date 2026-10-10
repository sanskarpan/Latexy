'use client'

import { useEntitlements } from '@/contexts/EntitlementsContext'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Link from 'next/link'
import { Plus, MoreHorizontal, ExternalLink, Trash2, Pencil, X, StickyNote, Search, Bell, Users, CalendarClock, BriefcaseBusiness, Sparkles, Copy, MailCheck } from 'lucide-react'
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
import {
  apiClient,
  type ApplicationInterview,
  type ApplicationReminder,
  type EmailStatusParseResponse,
  type JobAlert,
  type JobApplication,
  type OutreachDraftResponse,
  type OutreachChannel,
  type OutreachPurpose,
  type SavedJob,
  type TrackerCompany,
  type TrackerContact,
  type TrackerStats,
} from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import AddApplicationModal from '@/components/AddApplicationModal'
import LoadingSpinner from '@/components/LoadingSpinner'
import SessionLoadError from '@/components/SessionLoadError'
import { downloadBlob } from '@/lib/download'
import {
  requestExtensionCapture,
  validExtensionCaptureId,
  type ExtensionJobCapture,
} from '@/lib/extension-capture'

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

function createEmptyBoard(): Record<string, JobApplication[]> {
  return Object.fromEntries(COLUMNS.map((column) => [column.id, []]))
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
  onWorkflow: (app: JobApplication) => void
  onOutreach: (app: JobApplication) => void
  isDragging?: boolean
}

function ApplicationCard({ app, onDelete, onEdit, onStatusChange, onWorkflow, onOutreach, isDragging = false }: ApplicationCardProps) {
  const { can } = useEntitlements()
  const { attributes, listeners, setNodeRef, transform, transition, isDragging: sortableDragging } =
    useSortable({ id: app.id, disabled: !can('e05') })
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
    firstMenuItemRef.current?.parentElement?.querySelector<HTMLButtonElement>('button:not([disabled])')?.focus()
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
      const menuHeight = 128 // approx height of the action menu
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
      <div {...attributes} {...listeners} aria-disabled={!can('e05')} className={can('e05') ? 'cursor-grab active:cursor-grabbing' : ''}>
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
          disabled={!can('e05')}
          aria-describedby={!can('e05') ? `status-unavailable-${app.id}` : undefined}
          value={app.status}
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          onChange={(e) => { e.stopPropagation(); if (!can('e05')) return; onStatusChange(app.id, e.target.value) }}
          className="w-full cursor-pointer rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-1 text-[11px] text-fg-2 outline-none transition focus:border-accent"
        >
          {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        {!can('e05') && <p id={`status-unavailable-${app.id}`} className="mt-1 text-[10px] text-fg-3">Application changes are unavailable for your current plan or feature settings.</p>}
      </div>

      {/* Overflow menu — always visible on touch/coarse pointers and on keyboard focus */}
      <div className="absolute right-2 top-2 opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100">
        <button
          ref={menuTriggerRef}
          type="button"
          aria-label={`Actions for ${app.company_name}`}
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
                onClick={() => { if (!can('e05')) return; closeMenu(true); onEdit(app) }}
                className="flex w-full items-center gap-2 rounded-[var(--radius-md)] px-3 py-1.5 text-xs text-fg-2 transition hover:bg-surface-2"
                aria-description={!can('e05') ? 'Unavailable for your current plan or feature settings' : undefined}
                disabled={!can('e05')}
              >
                <Pencil size={12} /> Edit
                {!can('e05') && <span className="ml-1 text-[10px]">(Unavailable)</span>}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => { closeMenu(true); onWorkflow(app) }}
                className="flex w-full items-center gap-2 rounded-[var(--radius-md)] px-3 py-1.5 text-xs text-fg-2 transition hover:bg-surface-2"
              >
                <CalendarClock size={12} /> Follow-ups
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => { if (!can('e09')) return; closeMenu(true); onOutreach(app) }}
                className="flex w-full items-center gap-2 rounded-[var(--radius-md)] px-3 py-1.5 text-xs text-fg-2 transition hover:bg-surface-2"
                aria-description={!can('e09') ? 'Unavailable for your current plan or feature settings' : undefined}
                disabled={!can('e09')}
              >
                <Sparkles size={12} /> Draft outreach
                {!can('e09') && <span className="ml-1 text-[10px]">(Unavailable)</span>}
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
  onWorkflow: (app: JobApplication) => void
  onOutreach: (app: JobApplication) => void
}

function KanbanColumn({ columnId, label, colorClass, badgeClass, apps, onDelete, onEdit, onStatusChange, onWorkflow, onOutreach }: ColumnProps) {
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
            <ApplicationCard key={app.id} app={app} onDelete={onDelete} onEdit={onEdit} onStatusChange={onStatusChange} onWorkflow={onWorkflow} onOutreach={onOutreach} />
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

function PanelShell({ title, description, icon, children }: { title: string; description: string; icon: React.ReactNode; children: React.ReactNode }) {
  return <section className="space-y-4" aria-labelledby={`${title.toLowerCase().replace(/\\s+/g, '-')}-heading`}>
    <div className="flex items-center gap-2">
      <span className="grid h-8 w-8 place-items-center rounded-[var(--radius-md)] bg-accent-soft text-accent-strong">{icon}</span>
      <div><h2 id={`${title.toLowerCase().replace(/\\s+/g, '-')}-heading`} className="text-base font-semibold text-fg">{title}</h2><p className="text-xs text-fg-3">{description}</p></div>
    </div>
    {children}
  </section>
}

function SavedJobsPanel({ onTracked }: { onTracked: () => void }) {
  const { can } = useEntitlements()
  const [jobs, setJobs] = useState<SavedJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ company_name: '', role_title: '', job_url: '', job_description_text: '', notes: '' })
  const [editing, setEditing] = useState<SavedJob | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => { setLoading(true); setError(null); try { setJobs(await apiClient.listSavedJobs()) } catch (e) { setError(e instanceof Error ? e.message : 'Could not load saved jobs') } finally { setLoading(false) } }, [])
  useEffect(() => { void load() }, [load])
  const save = async (event: React.FormEvent) => { event.preventDefault(); if (!can('e06')) return; setBusy(true); try { const payload = { ...form, job_url: form.job_url || (editing ? null : undefined), job_description_text: form.job_description_text || (editing ? null : undefined), notes: form.notes || (editing ? null : undefined) }; if (editing) { const updated = await apiClient.updateSavedJob(editing.id, payload); setJobs((items) => items.map((item) => item.id === editing.id ? updated : item)); setEditing(null); toast.success('Saved job updated') } else { const job = await apiClient.createSavedJob(payload); setJobs((items) => [job, ...items]); toast.success('Job saved') }; setForm({ company_name: '', role_title: '', job_url: '', job_description_text: '', notes: '' }) } catch (e) { toast.error(e instanceof Error ? e.message : 'Could not save job') } finally { setBusy(false) } }
  const startEdit = (job: SavedJob) => { if (!can('e06')) return; setEditing(job); setForm({ company_name: job.company_name, role_title: job.role_title, job_url: job.job_url || '', job_description_text: job.job_description_text || '', notes: job.notes || '' }) }
  const remove = async (id: string) => { if (!window.confirm('Remove this saved job?')) return; try { await apiClient.deleteSavedJob(id); setJobs((items) => items.filter((item) => item.id !== id)); setSelected((ids) => ids.filter((item) => item !== id)) } catch { toast.error('Could not delete saved job') } }
  const bulkRemove = async () => { if (!selected.length || !window.confirm(`Remove ${selected.length} saved jobs?`)) return; setBusy(true); try { await apiClient.bulkDeleteSavedJobs(selected); setJobs((items) => items.filter((item) => !selected.includes(item.id))); setSelected([]); toast.success('Saved jobs removed') } catch { toast.error('Could not remove selected jobs') } finally { setBusy(false) } }
  const track = async (job: SavedJob) => { if (!can('e05') || !can('e06')) return; try { await apiClient.trackSavedJob(job.id); setJobs((items) => items.filter((item) => item.id !== job.id)); onTracked(); toast.success('Moved to applications') } catch (e) { toast.error(e instanceof Error ? e.message : 'Could not track job') } }
  return <PanelShell title="Saved jobs" description="Keep promising roles handy until you are ready to apply." icon={<BriefcaseBusiness size={16} />}>
    {error && <div role="alert" className="flex items-center justify-between gap-3 rounded border border-err/30 bg-err/10 px-3 py-2 text-xs text-err"><span>{error}</span><button type="button" onClick={() => void load()} className="font-semibold underline">Retry</button></div>}
    {!can('e06') && <p className="text-xs text-fg-3">Saving and editing jobs are unavailable for your current plan or feature settings.</p>}
    <form onSubmit={save} className="grid gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-4 sm:grid-cols-2" aria-label={editing ? 'Edit saved job' : 'Save a job'}>
      <input required value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} placeholder="Company" aria-label="Company" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <input required value={form.role_title} onChange={(e) => setForm({ ...form, role_title: e.target.value })} placeholder="Role title" aria-label="Role title" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <input type="url" value={form.job_url} onChange={(e) => setForm({ ...form, job_url: e.target.value })} placeholder="Job URL (optional)" aria-label="Job URL" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <textarea value={form.job_description_text} onChange={(e) => setForm({ ...form, job_description_text: e.target.value })} placeholder="Job description (optional)" aria-label="Job description" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Notes (optional)" aria-label="Notes" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <div className="flex gap-2 sm:col-span-2"><button disabled={!can('e06') || (busy)} className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-50" aria-description={!can('e06') ? 'Unavailable for your current plan or feature settings' : undefined}>{busy ? 'Saving…' : editing ? 'Update job' : 'Save job'}{!can('e06') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button>{editing && <button type="button" onClick={() => { setEditing(null); setForm({ company_name: '', role_title: '', job_url: '', job_description_text: '', notes: '' }) }} className="rounded border border-line px-3 py-2 text-xs text-fg-2">Cancel</button>}</div>
    </form>
    {loading ? <LoadingSpinner /> : jobs.length === 0 ? <div className="rounded-[var(--radius-lg)] border border-dashed border-line px-5 py-10 text-center text-sm text-fg-3">No saved jobs yet.</div> : <><div className="mb-2 flex items-center justify-between"><label className="flex items-center gap-2 text-xs text-fg-2"><input type="checkbox" checked={selected.length === jobs.length} onChange={(e) => setSelected(e.target.checked ? jobs.map((job) => job.id) : [])} aria-label="Select all saved jobs" /> Select all</label>{selected.length > 0 && <button type="button" disabled={busy} onClick={() => void bulkRemove()} className="rounded border border-err/30 px-3 py-1.5 text-xs font-semibold text-err">Remove selected ({selected.length})</button>}</div><div className="grid gap-2" role="list">{jobs.map((job) => <article key={job.id} role="listitem" className="flex flex-wrap items-center gap-3 rounded-[var(--radius-lg)] border border-line bg-surface p-4"><input type="checkbox" checked={selected.includes(job.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, job.id] : ids.filter((id) => id !== job.id))} aria-label={`Select ${job.role_title}`} /><div className="min-w-0 flex-1"><h3 className="truncate text-sm font-semibold text-fg">{job.role_title}</h3><p className="text-xs text-fg-2">{job.company_name}</p>{job.job_description_text && <p className="mt-1 line-clamp-2 text-xs text-fg-3">{job.job_description_text}</p>}{job.notes && <p className="mt-1 text-xs text-fg-3">{job.notes}</p>}</div>{job.job_url && <a href={job.job_url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent-strong">Open posting</a>}<button onClick={() => startEdit(job)} className="rounded border border-line px-2 py-1.5 text-xs text-fg-2" aria-description={!can('e06') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e06')}>Edit{!can('e06') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button><button onClick={() => void track(job)} className="rounded-[var(--radius-md)] bg-accent-soft px-3 py-1.5 text-xs font-semibold text-accent-strong" aria-description={!can('e05') || !can('e06') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e05') || !can('e06')}>Track application{(!can('e05') || !can('e06')) && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button><button onClick={() => void remove(job.id)} aria-label={`Delete ${job.role_title}`} className="rounded-[var(--radius-md)] p-1.5 text-err hover:bg-err/10"><Trash2 size={14} /></button></article>)}</div></>}
  </PanelShell>
}

function AlertsPanel() {
  const { can } = useEntitlements()
  const [alerts, setAlerts] = useState<JobAlert[]>([])
  const [form, setForm] = useState({ query: '', company_name: '', location: '', source_url: '', frequency: 'daily' as 'daily' | 'weekly' })
  const [editing, setEditing] = useState<JobAlert | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => { setLoading(true); setError(null); try { setAlerts(await apiClient.listAlerts()) } catch (e) { setError(e instanceof Error ? e.message : 'Could not load alerts') } finally { setLoading(false) } }, [])
  useEffect(() => { void load() }, [load])
  const save = async (event: React.FormEvent) => { event.preventDefault(); if (!can('e06')) return; try { if (editing) { const updated = await apiClient.updateAlert(editing.id, { ...form, company_name: form.company_name || null, location: form.location || null, source_url: form.source_url || null }); setAlerts((items) => items.map((item) => item.id === editing.id ? updated : item)); setEditing(null); toast.success('Alert updated') } else { const alert = await apiClient.createAlert({ ...form, company_name: form.company_name || undefined, location: form.location || undefined, source_url: form.source_url }); setAlerts((items) => [alert, ...items]); toast.success('Alert created') }; setForm({ query: '', company_name: '', location: '', source_url: '', frequency: 'daily' }) } catch (e) { toast.error(e instanceof Error ? e.message : 'Could not save alert') } }
  const startEdit = (alert: JobAlert) => { if (!can('e06')) return; setEditing(alert); setForm({ query: alert.query, company_name: alert.company_name || '', location: alert.location || '', source_url: alert.source_url, frequency: alert.frequency }) }
  const toggle = async (alert: JobAlert) => { if (!alert.active && !can('e06')) return; try { const updated = await apiClient.updateAlert(alert.id, { active: !alert.active }); setAlerts((items) => items.map((item) => item.id === alert.id ? updated : item)) } catch { toast.error('Could not update alert') } }
  const remove = async (id: string) => { if (!window.confirm('Delete this alert?')) return; try { await apiClient.deleteAlert(id); setAlerts((items) => items.filter((item) => item.id !== id)) } catch { toast.error('Could not delete alert') } }
  return <PanelShell title="Alerts" description="Get notified when it is time to review a saved search." icon={<Bell size={16} />}>
    <p className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg-2">Latexy does not scrape or discover jobs. Alerts are reminders to review the searches and source URLs you provide.</p>
    {error && <div role="alert" className="flex items-center justify-between gap-3 rounded border border-err/30 bg-err/10 px-3 py-2 text-xs text-err"><span>{error}</span><button type="button" onClick={() => void load()} className="font-semibold underline">Retry</button></div>}
    {!can('e06') && <p className="text-xs text-fg-3">Creating, editing, and resuming alerts are unavailable for your current plan or feature settings. You can still pause or delete alerts.</p>}
    <form onSubmit={save} className="grid gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-4 sm:grid-cols-2" aria-label={editing ? 'Edit job alert' : 'Create job alert'}>
      <input required value={form.query} onChange={(e) => setForm({ ...form, query: e.target.value })} placeholder="Search query" aria-label="Search query" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <input required type="url" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} placeholder="Source URL" aria-label="Source URL" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <input value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} placeholder="Company (optional)" aria-label="Alert company" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="Location (optional)" aria-label="Alert location" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg" />
      <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value as 'daily' | 'weekly' })} aria-label="Alert frequency" className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs text-fg"><option value="daily">Daily</option><option value="weekly">Weekly</option></select><div className="flex gap-2"><button className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg" aria-description={!can('e06') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e06')}>{editing ? 'Update alert' : 'Create alert'}{!can('e06') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button>{editing && <button type="button" onClick={() => { setEditing(null); setForm({ query: '', company_name: '', location: '', source_url: '', frequency: 'daily' }) }} className="rounded border border-line px-3 py-2 text-xs text-fg-2">Cancel</button>}</div>
    </form>
    {loading ? <LoadingSpinner /> : alerts.length === 0 ? <div className="rounded-[var(--radius-lg)] border border-dashed border-line px-5 py-10 text-center text-sm text-fg-3">No alerts yet.</div> : <div className="grid gap-2" role="list">{alerts.map((alert) => <article key={alert.id} role="listitem" className="flex flex-wrap items-center gap-3 rounded-[var(--radius-lg)] border border-line bg-surface p-4"><div className="min-w-0 flex-1"><h3 className="text-sm font-semibold text-fg">{alert.query}</h3><p className="text-xs text-fg-2">{[alert.company_name, alert.location].filter(Boolean).join(' · ') || 'All locations'} · {alert.frequency}</p><p className="text-[11px] text-fg-3">{alert.source_url}</p></div><button onClick={() => startEdit(alert)} className="rounded border border-line px-2 py-1.5 text-xs text-fg-2" aria-description={!can('e06') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e06')}>Edit{!can('e06') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button><button role="switch" aria-checked={alert.active} aria-label={`Alert ${alert.query}`} onClick={() => void toggle(alert)} className={`rounded-full px-3 py-1 text-xs ${alert.active ? 'bg-ok/10 text-ok' : 'bg-surface-2 text-fg-3'}`} aria-description={!alert.active && !can('e06') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!alert.active && !can('e06')}>{alert.active ? 'Active' : 'Paused'}{!alert.active && !can('e06') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button><button onClick={() => void remove(alert.id)} aria-label={`Delete alert ${alert.query}`} className="rounded-[var(--radius-md)] p-1.5 text-err hover:bg-err/10"><Trash2 size={14} /></button></article>)}</div>}
  </PanelShell>
}

function ContactsPanel() {
  const { can } = useEntitlements()
  const [contacts, setContacts] = useState<TrackerContact[]>([])
  const [companies, setCompanies] = useState<TrackerCompany[]>([])
  const [form, setForm] = useState({ name: '', role_title: '', email: '', phone: '', linkedin_url: '', notes: '', company_id: '' })
  const [companyForm, setCompanyForm] = useState({ name: '', website: '', notes: '' })
  const [editingContact, setEditingContact] = useState<TrackerContact | null>(null)
  const [editingCompany, setEditingCompany] = useState<TrackerCompany | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => { setLoading(true); setError(null); try { const [nextContacts, nextCompanies] = await Promise.all([apiClient.listTrackerContacts(), apiClient.listTrackerCompanies()]); setContacts(nextContacts); setCompanies(nextCompanies) } catch (e) { setError(e instanceof Error ? e.message : 'Could not load contacts') } finally { setLoading(false) } }, [])
  useEffect(() => { void load() }, [load])
  const saveContact = async (event: React.FormEvent) => { event.preventDefault(); if (!can('e08')) return; try { const payload = { ...form, role_title: form.role_title || (editingContact ? null : undefined), email: form.email || (editingContact ? null : undefined), phone: form.phone || (editingContact ? null : undefined), linkedin_url: form.linkedin_url || (editingContact ? null : undefined), notes: form.notes || (editingContact ? null : undefined), company_id: form.company_id || (editingContact ? null : undefined) }; if (editingContact) { const updated = await apiClient.updateTrackerContact(editingContact.id, payload); setContacts((items) => items.map((item) => item.id === editingContact.id ? updated : item)); setEditingContact(null); toast.success('Contact updated') } else { const contact = await apiClient.createTrackerContact(payload); setContacts((items) => [...items, contact].sort((a, b) => a.name.localeCompare(b.name))); toast.success('Contact added') }; setForm({ name: '', role_title: '', email: '', phone: '', linkedin_url: '', notes: '', company_id: '' }) } catch (e) { toast.error(e instanceof Error ? e.message : 'Could not save contact') } }
  const saveCompany = async (event: React.FormEvent) => { event.preventDefault(); if (!can('e08')) return; try { const payload = { ...companyForm, website: companyForm.website || (editingCompany ? null : undefined), notes: companyForm.notes || (editingCompany ? null : undefined) }; if (editingCompany) { const updated = await apiClient.updateTrackerCompany(editingCompany.id, payload); setCompanies((items) => items.map((item) => item.id === editingCompany.id ? updated : item)); setEditingCompany(null); toast.success('Company updated') } else { const company = await apiClient.createTrackerCompany(payload); setCompanies((items) => [...items, company].sort((a, b) => a.name.localeCompare(b.name))); toast.success('Company added') }; setCompanyForm({ name: '', website: '', notes: '' }) } catch (e) { toast.error(e instanceof Error ? e.message : 'Could not save company') } }
  const editContact = (contact: TrackerContact) => { if (!can('e08')) return; setEditingContact(contact); setForm({ name: contact.name, role_title: contact.role_title || '', email: contact.email || '', phone: contact.phone || '', linkedin_url: contact.linkedin_url || '', notes: contact.notes || '', company_id: contact.company_id || '' }) }
  const editCompany = (company: TrackerCompany) => { if (!can('e08')) return; setEditingCompany(company); setCompanyForm({ name: company.name, website: company.website || '', notes: company.notes || '' }) }
  const remove = async (id: string) => { if (!window.confirm('Delete this contact?')) return; try { await apiClient.deleteTrackerContact(id); setContacts((items) => items.filter((item) => item.id !== id)) } catch { toast.error('Could not delete contact') } }
  const removeCompany = async (id: string) => { if (!window.confirm('Delete this company? Contacts assigned to it will be detached.')) return; try { await apiClient.deleteTrackerCompany(id); setCompanies((items) => items.filter((item) => item.id !== id)); setContacts((items) => items.map((item) => item.company_id === id ? { ...item, company_id: null } : item)) } catch { toast.error('Could not delete company') } }
  return <PanelShell title="Contacts" description="Keep recruiters and interview contacts close to your applications." icon={<Users size={16} />}>
    {error && <div role="alert" className="flex items-center justify-between gap-3 rounded border border-err/30 bg-err/10 px-3 py-2 text-xs text-err"><span>{error}</span><button type="button" onClick={() => void load()} className="font-semibold underline">Retry</button></div>}
    {!can('e08') && <p className="text-xs text-fg-3">Adding and editing contacts and companies are unavailable for your current plan or feature settings.</p>}
    <div className="grid gap-4 lg:grid-cols-2"><form onSubmit={saveCompany} className="grid gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-4" aria-label={editingCompany ? 'Edit company' : 'Create company'}><h3 className="text-sm font-semibold text-fg">Companies</h3><input required value={companyForm.name} onChange={(e) => setCompanyForm({ ...companyForm, name: e.target.value })} placeholder="Company name" aria-label="Company name" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><input type="url" value={companyForm.website} onChange={(e) => setCompanyForm({ ...companyForm, website: e.target.value })} placeholder="Website (optional)" aria-label="Company website" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><textarea value={companyForm.notes} onChange={(e) => setCompanyForm({ ...companyForm, notes: e.target.value })} placeholder="Notes" aria-label="Company notes" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><div className="flex gap-2"><button className="rounded bg-accent px-3 py-2 text-xs font-semibold text-accent-fg" aria-description={!can('e08') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e08')}>{editingCompany ? 'Update company' : 'Add company'}{!can('e08') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button>{editingCompany && <button type="button" onClick={() => { setEditingCompany(null); setCompanyForm({ name: '', website: '', notes: '' }) }} className="rounded border border-line px-3 py-2 text-xs">Cancel</button>}</div>{companies.map((company) => <div key={company.id} className="flex items-center gap-2 text-xs"><span className="flex-1">{company.name}</span><button type="button" onClick={() => editCompany(company)} className="text-accent-strong" aria-description={!can('e08') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e08')}>Edit{!can('e08') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button><button type="button" onClick={() => void removeCompany(company.id)} className="text-err">Delete</button></div>)}</form><form onSubmit={saveContact} className="grid gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-4" aria-label={editingContact ? 'Edit contact' : 'Add tracker contact'}><h3 className="text-sm font-semibold text-fg">{editingContact ? 'Edit contact' : 'Add contact'}</h3><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Name" aria-label="Contact name" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><input value={form.role_title} onChange={(e) => setForm({ ...form, role_title: e.target.value })} placeholder="Role" aria-label="Contact role" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="Email" aria-label="Contact email" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="Phone" aria-label="Contact phone" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><input type="url" value={form.linkedin_url} onChange={(e) => setForm({ ...form, linkedin_url: e.target.value })} placeholder="LinkedIn URL" aria-label="LinkedIn URL" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Notes" aria-label="Contact notes" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg" /><select value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value })} aria-label="Contact company" className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg"><option value="">No company (detached)</option>{companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}</select><div className="flex gap-2"><button className="rounded bg-accent px-3 py-2 text-xs font-semibold text-accent-fg" aria-description={!can('e08') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e08')}>{editingContact ? 'Update contact' : 'Add contact'}{!can('e08') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button>{editingContact && <button type="button" onClick={() => { setEditingContact(null); setForm({ name: '', role_title: '', email: '', phone: '', linkedin_url: '', notes: '', company_id: '' }) }} className="rounded border border-line px-3 py-2 text-xs">Cancel</button>}</div></form></div>
    {loading ? <LoadingSpinner /> : contacts.length === 0 ? <div className="rounded-[var(--radius-lg)] border border-dashed border-line px-5 py-10 text-center text-sm text-fg-3">No contacts yet.</div> : <div className="grid gap-2 sm:grid-cols-2" role="list">{contacts.map((contact) => <article key={contact.id} role="listitem" className="flex items-start gap-3 rounded-[var(--radius-lg)] border border-line bg-surface p-4"><div className="min-w-0 flex-1"><h3 className="text-sm font-semibold text-fg">{contact.name}</h3><p className="text-xs text-fg-2">{contact.role_title || 'Contact'}{contact.email ? ` · ${contact.email}` : ''}</p>{contact.linkedin_url && <a href={contact.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent-strong">LinkedIn</a>}{contact.phone && <p className="text-xs text-fg-3">{contact.phone}</p>}{contact.notes && <p className="text-xs text-fg-3">{contact.notes}</p>}</div><button onClick={() => editContact(contact)} className="rounded border border-line px-2 py-1 text-xs" aria-description={!can('e08') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e08')}>Edit{!can('e08') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button><button onClick={() => void remove(contact.id)} aria-label={`Delete contact ${contact.name}`} className="rounded-[var(--radius-md)] p-1.5 text-err hover:bg-err/10"><Trash2 size={14} /></button></article>)}</div>}
  </PanelShell>
}

function datetimeLocal(iso: string) {
  const date = new Date(iso)
  const offset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function ApplicationWorkflowPanel({ app, onClose }: { app: JobApplication; onClose: () => void }) {
  const { can } = useEntitlements()
  const [reminders, setReminders] = useState<ApplicationReminder[]>([])
  const [interviews, setInterviews] = useState<ApplicationInterview[]>([])
  const [remindAt, setRemindAt] = useState('')
  const [reminderNote, setReminderNote] = useState('')
  const [editingReminder, setEditingReminder] = useState<ApplicationReminder | null>(null)
  const [editingInterview, setEditingInterview] = useState<ApplicationInterview | null>(null)
  const [interview, setInterview] = useState({ round_name: '', interview_format: 'video' as ApplicationInterview['interview_format'], starts_at: '', duration_minutes: '60', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', location: '', interviewers: '', notes: '' })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => { setLoading(true); setError(null); try { const [nextReminders, nextInterviews] = await Promise.all([apiClient.listApplicationReminders(app.id), apiClient.listApplicationInterviews(app.id)]); setReminders(nextReminders); setInterviews(nextInterviews) } catch (e) { setError(e instanceof Error ? e.message : 'Could not load follow-ups') } finally { setLoading(false) } }, [app.id])
  useEffect(() => { void load() }, [load])
  const saveReminder = async (event: React.FormEvent) => { event.preventDefault(); if (!can('e07')) return; try { const payload = { remind_at: new Date(remindAt).toISOString(), note: reminderNote || null }; const item = editingReminder ? await apiClient.updateApplicationReminder(app.id, editingReminder.id, payload) : await apiClient.createApplicationReminder(app.id, payload); setReminders((items) => editingReminder ? items.map((entry) => entry.id === item.id ? item : entry) : [...items, item]); setEditingReminder(null); setRemindAt(''); setReminderNote(''); toast.success(editingReminder ? 'Reminder rescheduled' : 'Reminder added') } catch (e) { toast.error(e instanceof Error ? e.message : 'Could not save reminder') } }
  const editReminder = (item: ApplicationReminder) => { if (!can('e07')) return; setEditingReminder(item); setRemindAt(datetimeLocal(item.remind_at)); setReminderNote(item.note || '') }
  const removeReminder = async (item: ApplicationReminder) => { if (!window.confirm('Delete this reminder?')) return; try { await apiClient.deleteApplicationReminder(app.id, item.id); setReminders((items) => items.filter((entry) => entry.id !== item.id)) } catch { toast.error('Could not delete reminder') } }
  const saveInterview = async (event: React.FormEvent) => { event.preventDefault(); if (!can('e07')) return; try { const payload = { round_name: interview.round_name, interview_format: interview.interview_format, starts_at: new Date(interview.starts_at).toISOString(), duration_minutes: Number(interview.duration_minutes), timezone: interview.timezone, location: interview.location || (editingInterview ? null : undefined), interviewers: interview.interviewers.split(',').map((value) => value.trim()).filter(Boolean), notes: interview.notes || (editingInterview ? null : undefined) }; const item = editingInterview ? await apiClient.updateApplicationInterview(app.id, editingInterview.id, payload) : await apiClient.createApplicationInterview(app.id, payload); setInterviews((items) => editingInterview ? items.map((entry) => entry.id === item.id ? item : entry) : [...items, item]); setEditingInterview(null); setInterview({ ...interview, round_name: '', starts_at: '', location: '', interviewers: '', notes: '' }); toast.success(editingInterview ? 'Interview updated' : 'Interview scheduled') } catch (e) { toast.error(e instanceof Error ? e.message : 'Could not save interview') } }
  const editInterview = (item: ApplicationInterview) => { if (!can('e07')) return; setEditingInterview(item); setInterview({ round_name: item.round_name, interview_format: item.interview_format, starts_at: datetimeLocal(item.starts_at), duration_minutes: String(item.duration_minutes), timezone: item.timezone, location: item.location || '', interviewers: item.interviewers.join(', '), notes: item.notes || '' }) }
  const removeInterview = async (item: ApplicationInterview) => { if (!window.confirm('Delete this interview?')) return; try { await apiClient.deleteApplicationInterview(app.id, item.id); setInterviews((items) => items.filter((entry) => entry.id !== item.id)) } catch { toast.error('Could not delete interview') } }
  const download = async (item: ApplicationInterview) => { try { const blob = await apiClient.downloadApplicationInterviewIcs(app.id, item.id); downloadBlob(blob, `interview-${item.id}.ics`) } catch { toast.error('Could not download calendar invite') } }
  return <div className="fixed inset-0 z-50 overflow-y-auto bg-[var(--overlay)] p-4" role="dialog" aria-modal="true" aria-labelledby="follow-ups-title" onClick={onClose}><div className="mx-auto my-8 w-full max-w-2xl rounded-[var(--radius-lg)] border border-line bg-bg p-5 shadow-[var(--shadow-2)]" onClick={(event) => event.stopPropagation()}><div className="flex items-start justify-between"><div><h2 id="follow-ups-title" className="text-lg font-semibold text-fg">Follow-ups · {app.company_name}</h2><p className="text-xs text-fg-2">{app.role_title}</p></div><button onClick={onClose} aria-label="Close follow-ups" className="rounded p-1 text-fg-3 hover:text-fg"><X size={16} /></button></div>{loading ? <div className="py-8"><LoadingSpinner /></div> : error ? <div role="alert" className="mt-5 rounded border border-err/30 bg-err/10 p-4 text-sm text-err"><p>{error}</p><button type="button" onClick={() => void load()} className="mt-3 rounded border border-err/30 px-3 py-1.5 text-xs font-semibold">Retry</button></div> : <div className="mt-5 grid gap-5 lg:grid-cols-2">{!can('e07') && <p className="text-xs text-fg-3 lg:col-span-2">Adding and updating reminders and interviews are unavailable for your current plan or feature settings.</p>}<div className="space-y-3"><h3 className="text-sm font-semibold text-fg">Reminders</h3><form onSubmit={saveReminder} className="space-y-2 rounded border border-line bg-surface p-3"><label className="block text-xs text-fg-2">{editingReminder ? 'Reschedule to' : 'Remind me'}<input required type="datetime-local" value={remindAt} onChange={(e) => setRemindAt(e.target.value)} className="mt-1 w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg" /></label><input value={reminderNote} onChange={(e) => setReminderNote(e.target.value)} placeholder="Note (optional)" aria-label="Reminder note" className="w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg" /><div className="flex gap-2"><button className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg" aria-description={!can('e07') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e07')}>{editingReminder ? 'Reschedule reminder' : 'Add reminder'}{!can('e07') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button>{editingReminder && <button type="button" onClick={() => { setEditingReminder(null); setRemindAt(''); setReminderNote('') }} className="rounded border border-line px-3 py-1.5 text-xs">Cancel</button>}</div></form>{reminders.map((item) => <div key={item.id} className="flex items-center gap-2 rounded border border-line p-2 text-xs"><span className="flex-1">{new Date(item.remind_at).toLocaleString()}{item.note ? ` · ${item.note}` : ''}</span><button onClick={() => editReminder(item)} className="text-accent-strong" aria-description={!can('e07') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e07')}>Edit{!can('e07') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button><button onClick={() => void removeReminder(item)} aria-label="Delete reminder" className="text-err"><Trash2 size={13} /></button></div>)}</div><div className="space-y-3"><h3 className="text-sm font-semibold text-fg">Interviews</h3><form onSubmit={saveInterview} className="space-y-2 rounded border border-line bg-surface p-3"><input required value={interview.round_name} onChange={(e) => setInterview({ ...interview, round_name: e.target.value })} placeholder="Round name" aria-label="Interview round" className="w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg" /><div className="grid grid-cols-2 gap-2"><select value={interview.interview_format} onChange={(e) => setInterview({ ...interview, interview_format: e.target.value as ApplicationInterview['interview_format'] })} aria-label="Interview format" className="rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg"><option value="video">Video</option><option value="phone">Phone</option><option value="onsite">On-site</option><option value="take_home">Take-home</option><option value="other">Other</option></select><input required type="number" min="5" value={interview.duration_minutes} onChange={(e) => setInterview({ ...interview, duration_minutes: e.target.value })} aria-label="Interview duration minutes" className="rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg" /></div><input required type="datetime-local" value={interview.starts_at} onChange={(e) => setInterview({ ...interview, starts_at: e.target.value })} aria-label="Interview start time" className="w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg" /><input value={interview.location} onChange={(e) => setInterview({ ...interview, location: e.target.value })} placeholder="Location or meeting link" aria-label="Interview location" className="w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg" /><input value={interview.interviewers} onChange={(e) => setInterview({ ...interview, interviewers: e.target.value })} placeholder="Interviewers (comma separated)" aria-label="Interviewers" className="w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg" /><textarea value={interview.notes} onChange={(e) => setInterview({ ...interview, notes: e.target.value })} placeholder="Notes" aria-label="Interview notes" className="w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg" /><div className="flex gap-2"><button className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg" aria-description={!can('e07') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e07')}>{editingInterview ? 'Update interview' : 'Schedule interview'}{!can('e07') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button>{editingInterview && <button type="button" onClick={() => { setEditingInterview(null); setInterview({ ...interview, round_name: '', starts_at: '', location: '', interviewers: '', notes: '' }) }} className="rounded border border-line px-3 py-1.5 text-xs">Cancel</button>}</div></form>{interviews.map((item) => <div key={item.id} className="rounded border border-line p-2 text-xs"><div className="flex items-center gap-2"><strong className="flex-1">{item.round_name}</strong><button onClick={() => editInterview(item)} className="text-accent-strong" aria-description={!can('e07') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={!can('e07')}>Edit{!can('e07') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button><button onClick={() => void download(item)} className="text-accent-strong">Add to calendar</button><button onClick={() => void removeInterview(item)} aria-label="Delete interview" className="text-err"><Trash2 size={13} /></button></div><p className="mt-1 text-fg-2">{new Date(item.starts_at).toLocaleString()} · {item.duration_minutes} min</p></div>)}</div></div>}</div></div>
}

function OutreachDraftPanel({ app, onClose }: { app: JobApplication; onClose: () => void }) {
  const { can } = useEntitlements()
  const [contacts, setContacts] = useState<TrackerContact[]>([])
  const [contactId, setContactId] = useState('')
  const [channel, setChannel] = useState<OutreachChannel>('email')
  const [purpose, setPurpose] = useState<OutreachPurpose>('referral_request')
  const [context, setContext] = useState('')
  const [draft, setDraft] = useState<OutreachDraftResponse | null>(null)
  const [errorSource, setErrorSource] = useState<'contacts' | 'generation' | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadContacts = useCallback(async () => { setLoading(true); setError(null); setErrorSource(null); try { setContacts(await apiClient.listTrackerContacts()) } catch (e) { setErrorSource('contacts'); setError(e instanceof Error ? e.message : 'Could not load contacts') } finally { setLoading(false) } }, [])
  useEffect(() => { void loadContacts() }, [loadContacts])
  const generateDraft = async () => { if (!can('e09')) return; setGenerating(true); setError(null); setErrorSource(null); try { setDraft(await apiClient.createOutreachDraft({ application_id: app.id, contact_id: contactId || null, channel, purpose, additional_context: context || null })) } catch (e) { setErrorSource('generation'); setError(e instanceof Error ? e.message : 'Could not generate outreach draft') } finally { setGenerating(false) } }
  const generate = async (event: React.FormEvent) => { event.preventDefault(); await generateDraft() }
  const copy = async (value: string, label: string) => { try { await navigator.clipboard.writeText(value); toast.success(`${label} copied`) } catch { toast.error(`Could not copy ${label.toLowerCase()}`) } }
  return <div className="fixed inset-0 z-50 overflow-y-auto bg-[var(--overlay)] p-4" role="dialog" aria-modal="true" aria-labelledby="outreach-title" onClick={onClose}><div className="mx-auto my-8 w-full max-w-2xl rounded-[var(--radius-lg)] border border-line bg-bg p-5 shadow-[var(--shadow-2)]" onClick={(event) => event.stopPropagation()}><div className="flex items-start justify-between"><div><h2 id="outreach-title" className="text-lg font-semibold text-fg">Draft outreach · {app.company_name}</h2><p className="text-xs text-fg-2">{app.role_title} · stage-aware draft</p></div><button onClick={onClose} aria-label="Close outreach draft" className="rounded p-1 text-fg-3 hover:text-fg"><X size={16} /></button></div><p className="mt-3 rounded border border-warn/30 bg-warn/5 px-3 py-2 text-xs text-fg-2"><strong className="text-fg">Editable draft — not sent.</strong> Latexy only creates copy for you to review. Nothing is sent or saved by this workflow.</p>{error && <div role="alert" className="mt-4 flex items-center justify-between gap-3 rounded border border-err/30 bg-err/10 px-3 py-2 text-xs text-err"><span>{error}</span><button type="button" onClick={() => errorSource === 'generation' ? void generateDraft() : void loadContacts()} className="font-semibold underline" aria-description={errorSource === 'generation' && !can('e09') ? 'Unavailable for your current plan or feature settings' : undefined} disabled={errorSource === 'generation' && !can('e09')}>Retry{errorSource === 'generation' && !can('e09') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button></div>}{loading ? <div className="py-8"><LoadingSpinner /></div> : <form onSubmit={generate} className="mt-4 space-y-3">{!can('e09') && <p className="text-xs text-fg-3">Generating outreach is unavailable for your current plan or feature settings. You can still edit and copy an existing draft.</p>}<div className="grid gap-3 sm:grid-cols-2"><label className="text-xs text-fg-2">Contact (optional)<select value={contactId} onChange={(event) => setContactId(event.target.value)} className="mt-1 w-full rounded border border-line bg-surface-2 px-2 py-2 text-xs text-fg"><option value="">No contact</option>{contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.name}{contact.role_title ? ` · ${contact.role_title}` : ''}</option>)}</select></label><label className="text-xs text-fg-2">Channel<select value={channel} onChange={(event) => setChannel(event.target.value as OutreachChannel)} className="mt-1 w-full rounded border border-line bg-surface-2 px-2 py-2 text-xs text-fg"><option value="email">Email</option><option value="linkedin">LinkedIn</option></select></label></div><label className="block text-xs text-fg-2">Purpose<select value={purpose} onChange={(event) => setPurpose(event.target.value as OutreachPurpose)} className="mt-1 w-full rounded border border-line bg-surface-2 px-2 py-2 text-xs text-fg"><option value="referral_request">Referral request</option><option value="follow_up">Follow-up</option><option value="thank_you">Thank you</option><option value="networking">Networking</option></select></label><label className="block text-xs text-fg-2">Additional context<textarea value={context} onChange={(event) => setContext(event.target.value)} maxLength={2000} rows={3} placeholder="Optional context for the draft" className="mt-1 w-full rounded border border-line bg-surface-2 px-2 py-2 text-xs text-fg" /></label><button disabled={!can('e09') || (generating)} className="rounded bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-50" aria-description={!can('e09') ? 'Unavailable for your current plan or feature settings' : undefined}>{generating ? 'Generating…' : draft ? 'Regenerate draft' : 'Generate draft'}{!can('e09') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button></form>}{draft && !loading && <div className="mt-5 space-y-3 border-t border-line pt-4"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-fg">Your editable draft</h3><span className="text-[11px] text-fg-3">{draft.stage} · {draft.channel}</span></div><div><label className="text-xs font-semibold text-fg-2" htmlFor="outreach-subject">Subject</label><div className="mt-1 flex gap-2"><input id="outreach-subject" value={draft.subject} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} className="min-w-0 flex-1 rounded border border-line bg-surface-2 px-2 py-2 text-xs text-fg" /><button type="button" onClick={() => void copy(draft.subject, 'Subject')} aria-label="Copy subject" className="rounded border border-line px-2 text-fg-2"><Copy size={13} /></button></div></div><div><label className="text-xs font-semibold text-fg-2" htmlFor="outreach-body">Body</label><div className="mt-1 flex gap-2"><textarea id="outreach-body" value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} rows={9} className="min-w-0 flex-1 rounded border border-line bg-surface-2 px-2 py-2 text-xs text-fg" /><button type="button" onClick={() => void copy(draft.body, 'Body')} aria-label="Copy body" className="self-start rounded border border-line px-2 py-2 text-fg-2"><Copy size={13} /></button></div></div>{draft.placeholders.length > 0 && <div className="rounded border border-warn/30 bg-warn/5 p-3 text-xs text-fg-2"><p className="font-semibold text-fg">Review checklist</p><ul className="mt-1 list-disc space-y-1 pl-5">{draft.placeholders.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}<p className="text-[11px] text-fg-3">Review and edit the subject and body before using them elsewhere. This draft is not sent.</p></div>}</div></div>
}

const MAX_FORWARDED_EMAIL_BYTES = 1_000_000

function EmailStatusReviewPanel({ onClose }: { onClose: () => void }) {
  const { can } = useEntitlements()
  const [rawEmail, setRawEmail] = useState('')
  const [result, setResult] = useState<EmailStatusParseResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [parsing, setParsing] = useState(false)
  const parseRequestRef = useRef(0)

  const closePanel = () => {
    parseRequestRef.current += 1
    setRawEmail('')
    setResult(null)
    setError(null)
    onClose()
  }

  const parseEmail = useCallback(async () => {
    if (!can('e10')) return
    const encodedBytes = new TextEncoder().encode(rawEmail).byteLength
    if (encodedBytes > MAX_FORWARDED_EMAIL_BYTES) {
      setResult(null)
      setError('This forwarded email is larger than 1 MB. Paste one smaller RFC5322 message to review it.')
      return
    }
    if (!rawEmail.trim()) {
      setResult(null)
      setError('Paste one raw forwarded email before reviewing it.')
      return
    }

    const requestId = ++parseRequestRef.current
    setParsing(true)
    setError(null)
    try {
      const parsed = await apiClient.parseTrackerEmailStatus({ raw_email: rawEmail })
      if (parseRequestRef.current === requestId) setResult(parsed)
    } catch (e) {
      if (parseRequestRef.current === requestId) {
        setResult(null)
        setError(e instanceof Error ? e.message : 'Could not parse forwarded email')
      }
    } finally {
      if (parseRequestRef.current === requestId) setParsing(false)
    }
  }, [can, rawEmail])

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-[var(--overlay)] p-4" role="dialog" aria-modal="true" aria-labelledby="email-status-review-title">
      <div className="mx-auto my-8 w-full max-w-2xl rounded-[var(--radius-lg)] border border-line bg-bg p-5 shadow-[var(--shadow-2)]">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="email-status-review-title" className="text-lg font-semibold text-fg">Review forwarded email</h2>
            <p className="text-xs text-fg-2">Review-only status suggestions from one raw RFC5322 message.</p>
          </div>
          <button type="button" onClick={closePanel} aria-label="Close email status review" className="rounded p-1 text-fg-3 hover:text-fg"><X size={16} /></button>
        </div>

        <div className="mt-4 rounded border-2 border-warn/40 bg-warn/10 p-3 text-xs text-fg-2">
          <p className="font-semibold text-fg">Review required — no automatic updates.</p>
          <p className="mt-1">Latexy only analyzes the message you paste here. It does not access your mailbox, send or forward mail, change an application, or retain the pasted message. No forwarding address or mailbox OAuth setup is provided by this review.</p>
        </div>

        {error && (
          <div role="alert" className="mt-4 flex items-center justify-between gap-3 rounded border border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
            <span>{error}</span>
            <button type="button" onClick={() => void parseEmail()} disabled={!can('e10') || (parsing)} className="font-semibold underline disabled:opacity-50" aria-description={!can('e10') ? 'Unavailable for your current plan or feature settings' : undefined}>Retry{!can('e10') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button>
          </div>
        )}

        <form onSubmit={(event) => { event.preventDefault(); void parseEmail() }} className="mt-4 space-y-3">
          {!can('e10') && <p className="text-xs text-fg-3">Email review is unavailable for your current plan or feature settings.</p>}
          <label htmlFor="raw-forwarded-email" className="block text-xs font-semibold text-fg-2">Raw forwarded email</label>
          <textarea id="raw-forwarded-email" value={rawEmail} onChange={(event) => { parseRequestRef.current += 1; setParsing(false); setResult(null); setError(null); setRawEmail(event.target.value) }} rows={10} maxLength={1_000_000} placeholder="Paste the complete RFC5322 message, including headers" className="w-full rounded border border-line bg-surface-2 px-3 py-2 font-mono text-xs text-fg placeholder:font-sans" />
          <p className="text-[11px] text-fg-3">Maximum size: 1 MB. One message at a time; review the suggestions before taking any action.</p>
          <button type="submit" disabled={!can('e10') || (parsing)} className="rounded bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-50" aria-description={!can('e10') ? 'Unavailable for your current plan or feature settings' : undefined}>{parsing ? 'Reviewing…' : 'Review email'}{!can('e10') && <span className="ml-1 text-[10px]">(Unavailable)</span>}</button>
        </form>

        {result && (
          <section aria-labelledby="email-status-results-title" className="mt-5 border-t border-line pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 id="email-status-results-title" className="text-sm font-semibold text-fg">Suggested details</h3>
              <span className="rounded-full bg-warn/10 px-2 py-1 text-[10px] font-semibold text-warn">Review required</span>
            </div>
            <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
              <div className="rounded border border-line bg-surface p-2"><dt className="text-fg-3">Suggested status</dt><dd className="mt-1 font-semibold text-fg">{result.status ?? 'Not detected'}</dd></div>
              <div className="rounded border border-line bg-surface p-2"><dt className="text-fg-3">Overall confidence</dt><dd className="mt-1 font-semibold text-fg">{Math.round(result.confidence * 100)}%</dd></div>
              <div className="rounded border border-line bg-surface p-2"><dt className="text-fg-3">Suggested company</dt><dd className="mt-1 font-semibold text-fg">{result.company ?? 'Not detected'} <span className="font-normal text-fg-3">({Math.round(result.company_confidence * 100)}%)</span></dd></div>
              <div className="rounded border border-line bg-surface p-2"><dt className="text-fg-3">Suggested role</dt><dd className="mt-1 font-semibold text-fg">{result.role ?? 'Not detected'} <span className="font-normal text-fg-3">({Math.round(result.role_confidence * 100)}%)</span></dd></div>
            </dl>
            <div className="mt-4 rounded border border-line bg-surface p-3">
              <h4 className="text-xs font-semibold text-fg">Canonical evidence</h4>
              {result.evidence.length > 0 ? <ul className="mt-2 space-y-2 text-xs text-fg-2">{result.evidence.map((item, index) => <li key={`${item.signal}-${index}`}><span className="font-semibold text-fg">{item.signal}</span><span className="ml-1">· {item.source}</span></li>)}</ul> : <p className="mt-2 text-xs text-fg-3">No canonical evidence was detected.</p>}
            </div>
            <p className="mt-3 text-[11px] font-semibold text-warn">Nothing has been applied to your tracker. This result is a suggestion for your review only.</p>
          </section>
        )}
      </div>
    </div>
  )
}

export default function TrackerPage() {
  const { can, loaded: capabilitiesLoaded } = useEntitlements()
  const canRef = useRef(can)
  canRef.current = can
  const { session, isPending: sessionLoading, error: sessionError } = useRequireAuth()

  const [boardData, setBoardData] = useState<Record<string, JobApplication[]>>(createEmptyBoard)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [extensionCapture, setExtensionCapture] = useState<ExtensionJobCapture | null>(null)
  const extensionCaptureRequestedRef = useRef(false)
  const [editingApp, setEditingApp] = useState<JobApplication | null>(null)
  const [workflowApp, setWorkflowApp] = useState<JobApplication | null>(null)
  const [outreachApp, setOutreachApp] = useState<JobApplication | null>(null)
  const [emailStatusReviewOpen, setEmailStatusReviewOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'board' | 'saved' | 'alerts' | 'contacts'>('board')
  const [staleApps, setStaleApps] = useState<Array<JobApplication & { days_since_update: number }>>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [dragSourceCol, setDragSourceCol] = useState<string | null>(null)
  const dragSnapshotRef = useRef<Record<string, JobApplication[]> | null>(null)
  const boardOwnerRef = useRef<string | null>(null)
  const statusMutationRef = useRef<Record<string, number>>({})
  const boardGenerationRef = useRef(0)
  const boardRequestVersionRef = useRef(0)
  const staleRequestVersionRef = useRef(0)
  const trackerMountedRef = useRef(false)
  const boardIdentityOwnerRef = useRef<string | null>(session?.user?.id ?? null)
  const acceptedBoardIdentityRef = useRef<{ ownerId: string | null; generation: number } | null>(null)
  const acceptedStaleIdentityRef = useRef<{ ownerId: string | null; generation: number } | null>(null)

  const trackerOwnerId = session?.user?.id ?? null
  const ownerTransition = boardIdentityOwnerRef.current !== trackerOwnerId
  if (ownerTransition) {
    boardIdentityOwnerRef.current = trackerOwnerId
    boardGenerationRef.current += 1
    boardRequestVersionRef.current += 1
    staleRequestVersionRef.current += 1
  }

  // Keep owner identity current during render as well as after effects. This
  // closes the small window where a delayed mutation could otherwise observe
  // the previous account before the session effect runs.
  boardOwnerRef.current = session?.user?.id ?? null

  const boardIdentityAccepted = acceptedBoardIdentityRef.current
  const staleIdentityAccepted = acceptedStaleIdentityRef.current
  const boardReadyForCurrentOwner = boardIdentityAccepted?.ownerId === trackerOwnerId
    && boardIdentityAccepted.generation === boardGenerationRef.current
  const staleReadyForCurrentOwner = staleIdentityAccepted?.ownerId === trackerOwnerId
    && staleIdentityAccepted.generation === boardGenerationRef.current
  const visibleBoardData = boardReadyForCurrentOwner ? boardData : createEmptyBoard()
  const visibleStaleApps = staleReadyForCurrentOwner ? staleApps : []

  useEffect(() => {
    trackerMountedRef.current = true
    return () => {
      trackerMountedRef.current = false
      boardRequestVersionRef.current += 1
      staleRequestVersionRef.current += 1
    }
  }, [])

  useEffect(() => {
    setBoardData(createEmptyBoard())
    setStaleApps([])
    setLoadError(null)
    setIsLoading(Boolean(trackerOwnerId))
    setActiveId(null)
    setDragSourceCol(null)
    dragSnapshotRef.current = null
  }, [trackerOwnerId])

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

  useEffect(() => {
    if (!session || !capabilitiesLoaded || extensionCaptureRequestedRef.current) return
    const currentUrl = new URL(window.location.href)
    const captureId = currentUrl.searchParams.get('capture_id')
    if (!captureId) return
    extensionCaptureRequestedRef.current = true
    currentUrl.searchParams.delete('capture_id')
    window.history.replaceState({}, '', `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`)

    if (!validExtensionCaptureId(captureId)) {
      toast.error('The browser-extension capture link is invalid.')
      return
    }
    if (!can('e13') || !can('e05')) { toast.error('Job Companion application import is unavailable for your current plan or feature settings.'); return }
    void requestExtensionCapture(captureId)
      .then((capture) => {
        if (!canRef.current('e13') || !canRef.current('e05')) return
        setExtensionCapture(capture)
        setShowAddModal(true)
        toast.success('Job posting imported — review it before saving')
      })
      .catch((error) => {
        toast.error(error instanceof Error ? error.message : 'Could not import extension capture')
      })
  }, [can, capabilitiesLoaded, session])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )


  const loadBoard = useCallback(async () => {
    const ownerId = session?.user?.id ?? null
    if (!ownerId || boardOwnerRef.current !== ownerId) return
    const generation = boardGenerationRef.current
    const requestVersion = ++boardRequestVersionRef.current
    const isCurrent = () => trackerMountedRef.current
      && boardOwnerRef.current === ownerId
      && boardIdentityOwnerRef.current === ownerId
      && boardGenerationRef.current === generation
      && boardRequestVersionRef.current === requestVersion
    setIsLoading(true)
    setLoadError(null)
    try {
      const listResp = await apiClient.listApplications()
      if (!isCurrent()) return
      const nextBoard = listResp.by_status as Record<string, JobApplication[]>
      acceptedBoardIdentityRef.current = { ownerId, generation }
      setBoardData(nextBoard)
    } catch (error) {
      if (!isCurrent()) return
      setLoadError(error instanceof Error ? error.message : 'Failed to load tracker')
      toast.error('Failed to load tracker')
    } finally {
      if (isCurrent()) setIsLoading(false)
    }
  }, [session])

  useEffect(() => {
    loadBoard()
  }, [loadBoard])

  const loadStaleApplications = useCallback(async () => {
    const ownerId = session?.user?.id ?? null
    if (!ownerId || boardOwnerRef.current !== ownerId) return
    const generation = boardGenerationRef.current
    const requestVersion = ++staleRequestVersionRef.current
    const isCurrent = () => trackerMountedRef.current
      && boardOwnerRef.current === ownerId
      && boardIdentityOwnerRef.current === ownerId
      && boardGenerationRef.current === generation
      && staleRequestVersionRef.current === requestVersion
    try {
      const stale = await apiClient.listStaleApplications(14)
      if (isCurrent()) {
        acceptedStaleIdentityRef.current = { ownerId, generation }
        setStaleApps(stale)
      }
    } catch {
      if (isCurrent()) setStaleApps([])
    }
  }, [session])

  useEffect(() => {
    void loadStaleApplications()
  }, [boardData, loadStaleApplications])

  // Find which column an app lives in
  const findColumn = useCallback(
    (appId: string): string | null => {
      for (const [colId, apps] of Object.entries(visibleBoardData)) {
        if (apps.some((a) => a.id === appId)) return colId
      }
      return null
    },
    [visibleBoardData]
  )

  // Find app by id across all columns
  const findApp = useCallback(
    (appId: string): JobApplication | undefined => {
      for (const apps of Object.values(visibleBoardData)) {
        const a = apps.find((x) => x.id === appId)
        if (a) return a
      }
    },
    [visibleBoardData]
  )

  const handleDragStart = (event: DragStartEvent) => {
    if (!canRef.current('e05')) return
    const id = event.active.id as string
    dragSnapshotRef.current = boardData
    setActiveId(id)
    setDragSourceCol(findColumn(id))
  }

  const restoreCancelledDrag = () => {
    const snapshot = dragSnapshotRef.current
    dragSnapshotRef.current = null
    setActiveId(null)
    setDragSourceCol(null)
    if (snapshot) {
      setBoardData(snapshot)
    }
  }

  const handleDragOver = (event: DragOverEvent) => {
    if (!canRef.current('e05')) { restoreCancelledDrag(); return }
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
      const next = {
        ...prev,
        [activeCol]: prev[activeCol].filter((a) => a.id !== activeId),
        [overCol]: [...prev[overCol], { ...app, status: overCol }],
      }
      return next
    })
  }

  const handleDragEnd = async (event: DragEndEvent) => {
    if (!canRef.current('e05')) { restoreCancelledDrag(); return }
    const { active, over } = event
    const sourceCol = dragSourceCol
    setActiveId(null)
    setDragSourceCol(null)
    if (!over) {
      restoreCancelledDrag()
      return
    }

    const activeId = active.id as string
    const overId = over.id as string

    const finalCol = COLUMNS.find((c) => c.id === overId)?.id ?? findColumn(overId)
    if (!finalCol) {
      restoreCancelledDrag()
      return
    }

    if (!sourceCol) {
      restoreCancelledDrag()
      return
    }

    // Within-column drop → reorder and remember it. The board has no backend
    // position field, so the order is persisted in the browser and the Sort
    // control switches to "Manual" so it actually displays (no silent snap-back).
    if (sourceCol === finalCol) {
      const displayed = filteredBoard[finalCol] ?? []
      const oldIndex = displayed.findIndex((a) => a.id === activeId)
      if (oldIndex === -1) {
        dragSnapshotRef.current = null
        return
      }
      let newIndex = displayed.findIndex((a) => a.id === overId)
      if (newIndex === -1) newIndex = displayed.length - 1 // dropped on the column body → end
      if (oldIndex !== newIndex) {
        const reordered = arrayMove(displayed, oldIndex, newIndex)
        persistManualOrder({ ...manualOrder, [finalCol]: reordered.map((a) => a.id) })
      }
      if (sortBy !== 'manual') setSortBy('manual')
      dragSnapshotRef.current = null
      return
    }

    try {
      await apiClient.updateApplicationStatus(activeId, finalCol)
      dragSnapshotRef.current = null
    } catch {
      toast.error('Failed to move card — reverting')
      restoreCancelledDrag()
      void loadBoard()
    }
  }

  // Non-drag status change (from the card <select>) — keyboard / touch accessible
  const handleStatusChange = useCallback(async (id: string, newStatus: string) => {
    if (!canRef.current('e05')) return
    const sourceCol = findColumn(id)
    if (!sourceCol || sourceCol === newStatus) return
    const app = boardData[sourceCol]?.find((a) => a.id === id)
    if (!app) return
    const sourceIndex = boardData[sourceCol].findIndex((item) => item.id === id)
    const mutationOwnerId = boardOwnerRef.current
    const mutationToken = (statusMutationRef.current[id] ?? 0) + 1
    statusMutationRef.current[id] = mutationToken
    setBoardData((prev) => {
      const next = {
        ...prev,
        [sourceCol]: prev[sourceCol].filter((a) => a.id !== id),
        [newStatus]: [{ ...app, status: newStatus }, ...(prev[newStatus] ?? [])],
      }
      return next
    })
    try {
      await apiClient.updateApplicationStatus(id, newStatus)
    } catch {
      // A newer mutation for this card, or an authenticated owner switch,
      // makes this failure stale. Do not undo newer local/server intent.
      if (
        statusMutationRef.current[id] !== mutationToken ||
        boardOwnerRef.current !== mutationOwnerId
      ) return
      toast.error('Failed to move card — reverting')
      setBoardData((current) => {
        if (
          statusMutationRef.current[id] !== mutationToken ||
          boardOwnerRef.current !== mutationOwnerId
        ) return current
        const currentApp = Object.values(current).flat().find((item) => item.id === id)
        // A newer delete or status update owns the current state. Never
        // resurrect a card that is gone or no longer reflects this attempt.
        if (!currentApp || currentApp.status !== newStatus) return current
        const next = Object.fromEntries(
          Object.entries(current).map(([column, apps]) => [column, apps.filter((item) => item.id !== id)]),
        ) as Record<string, JobApplication[]>
        const restored = { ...(currentApp ?? app), status: sourceCol }
        const target = [...(next[sourceCol] ?? [])]
        target.splice(Math.min(sourceIndex, target.length), 0, restored)
        return { ...next, [sourceCol]: target }
      })
    }
  }, [boardData, findColumn])

  const handleDelete = useCallback((id: string) => {
    const col = findColumn(id)
    if (!col) return
    const index = boardData[col].findIndex((a) => a.id === id)
    const app = boardData[col][index]
    if (!app) return
    const deleteOwnerId = session?.user?.id ?? null

    // Optimistic remove — the real API call is deferred so an "Undo" can cancel it.
    // Stats are recomputed locally in lockstep with the board so the stats strip
    // reflects the deletion immediately, rather than lagging behind the deferred
    // network delete + refetch below (or requiring a manual reload to catch up).
    const boardAfterDelete = { ...boardData, [col]: boardData[col].filter((a) => a.id !== id) }
    setBoardData(boardAfterDelete)

    let undone = false
    const timer = setTimeout(async () => {
      if (undone) return
      // A session switch can leave this timer alive after the board has moved
      // to another owner. Never issue the old owner's destructive request.
      if (boardOwnerRef.current !== deleteOwnerId) return
      try {
        await apiClient.deleteApplication(id)
      } catch {
        if (boardOwnerRef.current !== deleteOwnerId) return
        toast.error('Failed to delete — restoring')
        // Restore only the application whose delete failed. Replacing the
        // whole captured board here could erase newer local mutations (for
        // example, a status change made while the deferred delete was in
        // flight). If a refresh or another mutation already restored it,
        // avoid inserting a duplicate card.
        setBoardData((current) => {
          // Never restore a card into a different authenticated user's board
          // if the session changed while the deferred request was pending.
          if (boardOwnerRef.current !== deleteOwnerId) return current
          const alreadyPresent = Object.values(current).some((apps) => apps.some((item) => item.id === id))
          if (alreadyPresent) return current
          const currentColumn = current[col] ?? []
          const restored = [...currentColumn]
          restored.splice(Math.min(index, restored.length), 0, app)
          return { ...current, [col]: restored }
        })
      }
    }, 5000)

    toast('Application deleted', {
      duration: 5000,
      action: {
        label: 'Undo',
        onClick: () => {
          undone = true
          clearTimeout(timer)
          if (boardOwnerRef.current !== deleteOwnerId) return
          // Reinsert at the original position within its column.
          setBoardData((prev) => {
            if (boardOwnerRef.current !== deleteOwnerId) return prev
            const alreadyPresent = Object.values(prev).some((apps) => apps.some((item) => item.id === id))
            if (alreadyPresent) return prev
            const next = [...(prev[col] ?? [])]
            next.splice(Math.min(index, next.length), 0, app)
            const restored = { ...prev, [col]: next }
            return restored
          })
        },
      },
    })
  }, [boardData, findColumn, session])

  const handleAppCreated = useCallback((app: JobApplication) => {
    setBoardData((prev) => {
      const next = {
        ...prev,
        [app.status]: [app, ...(prev[app.status] ?? [])],
      }
      return next
    })
  }, [])

  const activeApp = activeId ? findApp(activeId) : null

  const filtersActive = searchQuery.trim() !== '' || onlyThisWeek || atsMin > 0

  // Client-side view over boardData: search + filters + sort. Cross-column drag and
  // status changes still mutate boardData directly, so this only affects presentation.
  const totalApps = useMemo(
    () => Object.values(visibleBoardData).reduce((sum, apps) => sum + apps.length, 0),
    [visibleBoardData],
  )
  const stats = useMemo(() => computeStatsFromBoard(visibleBoardData), [visibleBoardData])

  const filteredBoard = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    const weekAgo = Date.now() - 7 * 86400000
    const out: Record<string, JobApplication[]> = {}
    for (const col of COLUMNS) {
      let apps = (visibleBoardData[col.id] ?? []).filter((a) => {
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
  }, [visibleBoardData, searchQuery, onlyThisWeek, atsMin, sortBy, manualOrder])

  if (sessionLoading || (isLoading && session)) {
    return (
      <div className="flex h-[70vh] items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (sessionError && !session) return <SessionLoadError area="Application tracker" />

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
            onClick={() => { if (can('e10')) setEmailStatusReviewOpen(true) }}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2"
            aria-description={!can('e10') ? 'Unavailable for your current plan or feature settings' : undefined}
            disabled={!can('e10')}
          >
            <MailCheck size={13} />
            Review forwarded email
            {!can('e10') && <span className="ml-1 text-[10px]">(Unavailable)</span>}
          </button>
          <button
            type="button"
            onClick={() => { if (can('e05')) setShowAddModal(true) }}
            className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 flex items-center gap-1.5"
            aria-description={!can('e05') ? 'Unavailable for your current plan or feature settings' : undefined}
            disabled={!can('e05')}
          >
            <Plus size={13} />
            Add Application
            {!can('e05') && <span className="ml-1 text-[10px]">(Unavailable)</span>}
          </button>
        </div>
      </section>

      {(!can('e05') || !can('e10')) && <p className="text-xs text-fg-3">Actions marked unavailable are disabled for your current plan or feature settings.</p>}

      {/* Stats */}
      <StatsBar stats={stats} />

      <nav aria-label="Tracker sections" className="flex flex-wrap gap-1 rounded-[var(--radius-lg)] border border-line bg-bg p-1">
        {([
          ['board', 'Board'],
          ['saved', 'Saved jobs'],
          ['alerts', 'Alerts'],
          ['contacts', 'Contacts'],
        ] as const).map(([value, label]) => (
          <button key={value} type="button" aria-current={activeTab === value ? 'page' : undefined} onClick={() => setActiveTab(value)} className={`rounded-[var(--radius-md)] px-3 py-2 text-xs font-semibold transition ${activeTab === value ? 'bg-accent text-accent-fg' : 'text-fg-2 hover:bg-surface-2'}`}>{label}</button>
        ))}
      </nav>

      {activeTab === 'board' && visibleStaleApps.length > 0 && (
        <section aria-labelledby="stale-follow-ups-heading" className="rounded-[var(--radius-lg)] border border-warn/30 bg-warn/5 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 id="stale-follow-ups-heading" className="text-sm font-semibold text-fg">Needs a follow-up</h2><p className="text-xs text-fg-2">You have not recorded an update for these applications in 14+ days. This is not an employer-response signal.</p></div><span className="rounded-full bg-warn/10 px-2 py-1 text-[10px] font-semibold text-warn">{visibleStaleApps.length}</span></div>
          <div className="mt-2 flex flex-wrap gap-2">{visibleStaleApps.slice(0, 5).map((stale) => <button key={stale.id} type="button" onClick={() => setWorkflowApp(stale)} className="rounded-[var(--radius-md)] border border-warn/30 bg-surface px-2.5 py-1.5 text-left text-xs text-fg hover:bg-surface-2"><span className="font-semibold">{stale.company_name}</span><span className="ml-1 text-fg-3">{stale.days_since_update}d since your last update · {can('e07') ? 'Add reminder' : 'View follow-ups'}</span></button>)}</div>
        </section>
      )}

      {activeTab === 'board' ? <>
      {loadError && (
        <section
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.07] px-4 py-3"
        >
          <div>
            <p className="text-sm font-semibold text-err">Tracker data could not be loaded</p>
            <p className="mt-0.5 text-xs text-fg-2">
              {totalApps > 0
                ? 'Showing the last data loaded in this session. Retry to refresh it.'
                : loadError}
            </p>
          </div>
          <button
            type="button"
            onClick={() => { void loadBoard() }}
            disabled={isLoading}
            className="rounded-[var(--radius-md)] border border-err/30 px-3 py-1.5 text-xs font-semibold text-err transition hover:bg-err/10 disabled:opacity-50"
          >
            {isLoading ? 'Retrying…' : 'Retry'}
          </button>
        </section>
      )}

      {loadError && totalApps === 0 ? (
        <div className="rounded-[var(--radius-lg)] border border-line bg-bg px-6 py-16 text-center">
          <h2 className="text-lg font-semibold text-fg">Tracker unavailable</h2>
          <p className="mt-2 text-sm text-fg-2">Retry the request above instead of creating duplicate data.</p>
        </div>
      ) : totalApps === 0 ? (
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
            onClick={() => { if (can('e05')) setShowAddModal(true) }}
            className="mt-2 flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110"
            aria-description={!can('e05') ? 'Unavailable for your current plan or feature settings' : undefined}
            disabled={!can('e05')}
          >
            <Plus size={13} />
            Add your first application
            {!can('e05') && <span className="ml-1 text-[10px]">(Unavailable)</span>}
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
          onDragCancel={restoreCancelledDrag}
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
                onWorkflow={setWorkflowApp}
                onOutreach={setOutreachApp}
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
      )} </> : activeTab === 'saved' ? <SavedJobsPanel onTracked={() => { void loadBoard() }} /> : activeTab === 'alerts' ? <AlertsPanel /> : <ContactsPanel />}

      {/* Add modal */}
      {showAddModal && (
        <AddApplicationModal
          onClose={() => {
            setShowAddModal(false)
            setExtensionCapture(null)
          }}
          onCreated={(app) => {
            handleAppCreated(app)
            setExtensionCapture(null)
          }}
          prefillCapture={extensionCapture}
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
          }}
        />
      )}
      {workflowApp && <ApplicationWorkflowPanel app={workflowApp} onClose={() => setWorkflowApp(null)} />}
      {outreachApp && <OutreachDraftPanel app={outreachApp} onClose={() => setOutreachApp(null)} />}
      {emailStatusReviewOpen && <EmailStatusReviewPanel onClose={() => setEmailStatusReviewOpen(false)} />}
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
  const { can } = useEntitlements()
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
    if (!can('e05')) return
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
          {!can('e05') && <p className="text-xs text-fg-3">Application changes are unavailable for your current plan or feature settings.</p>}
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
            <button type="submit" disabled={!can('e05') || (isSubmitting)}
              className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50" aria-description={!can('e05') ? 'Unavailable for your current plan or feature settings' : undefined}>
              {isSubmitting ? 'Saving…' : 'Save Changes'}
              {!can('e05') && <span className="ml-1 text-[10px]">(Unavailable)</span>}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
