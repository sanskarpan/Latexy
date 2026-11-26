'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminSavedView,
  type AdminSavedViewCatalog,
  type AdminSavedViewScope,
  type AdminSavedViewScopeCatalogEntry,
  type AdminSegment,
  type AdminSegmentCondition,
  type AdminSegmentDefinition,
  type AdminSegmentField,
  type AdminSegmentFieldsResponse,
  type AdminSegmentPreview,
  type AdminSegmentPreviewGroup,
} from '@/lib/api-client'

const SCOPES: Array<{ id: AdminSavedViewScope; label: string }> = [
  { id: 'analytics', label: 'Analytics' },
  { id: 'operations', label: 'Operations' },
  { id: 'quality', label: 'Quality' },
  { id: 'billing', label: 'Revenue' },
  { id: 'subscriptions', label: 'Subscriptions' },
  { id: 'email', label: 'Email Health' },
  { id: 'growth', label: 'Growth & Cost' },
  { id: 'customers', label: 'Customers' },
]

const DRAFT_CONDITION: AdminSegmentCondition = { field: 'plan', operator: 'eq', value: 'pro' }

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function isConflict(error: unknown): boolean {
  return errorMessage(error).includes('409')
}

function scopeLabel(scope: AdminSavedViewScope): string {
  return SCOPES.find((entry) => entry.id === scope)?.label ?? scope
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ')
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return value == null ? '' : String(value)
}

function readFilters(filters: Record<string, unknown> | undefined): string {
  if (!filters) return ''
  return Object.entries(filters)
    .map(([key, value]) => `${key}=${formatValue(value)}`)
    .join(' · ')
}

/** Build a compact, reviewable summary for a saved view selector. */
export function savedViewSummary(view: AdminSavedView): string {
  const bits = [scopeLabel(view.scope)]
  if (view.range_days) bits.push(`${view.range_days}d`)
  const filterText = readFilters(view.filters)
  if (filterText) bits.push(filterText)
  return bits.join(' · ')
}

function parseViewFilterValue(key: string, raw: string): unknown {
  const value = raw.trim()
  if (key === 'verified') return value !== 'false'
  if (value.includes(',')) return value.split(',').map((item) => item.trim()).filter(Boolean)
  return value
}

function filtersFromRows(rows: Array<{ key: string; value: string }>): Record<string, unknown> {
  const filters: Record<string, unknown> = {}
  for (const row of rows) {
    if (!row.key || !row.value.trim()) continue
    filters[row.key] = parseViewFilterValue(row.key, row.value)
  }
  return filters
}

function conditionValue(field: AdminSegmentField | undefined, operator: string, raw: string): unknown {
  if (!field) return raw
  if (field.type === 'boolean') return raw === 'true'
  if (operator === 'in' || operator === 'not_in') {
    return raw.split(',').map((item) => item.trim()).filter(Boolean)
  }
  return raw.trim()
}

// --------------------------------------------------------------------------- //
//  Tab-level picker                                                            //
// --------------------------------------------------------------------------- //

export function AdminSavedViewsBar({
  scope,
  onApply,
  onManage,
  refreshKey = 0,
}: {
  scope: AdminSavedViewScope
  onApply: (view: AdminSavedView) => void
  onManage: () => void
  refreshKey?: number
}) {
  const [views, setViews] = useState<AdminSavedView[]>([])
  const [selected, setSelected] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await apiClient.getAdminSavedViews({ scope, limit: 100 })
      setViews(response.items)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [scope])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  useEffect(() => {
    if (views.length === 0) return
    const requested = new URLSearchParams(window.location.search).get('view')
    const view = requested
      ? views.find((item) => item.id === requested)
      : views.find((item) => item.is_default)
    if (view) {
      setSelected(view.id)
      onApply(view)
    }
  }, [views, onApply])

  const selectedView = views.find((view) => view.id === selected) ?? null

  return (
    <div className="mb-4 flex flex-wrap items-end gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-3">
      <div className="min-w-[220px] flex-1">
        <label className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3" htmlFor={`saved-view-${scope}`}>
          Saved {scopeLabel(scope).toLowerCase()} views
        </label>
        <select
          id={`saved-view-${scope}`}
          value={selected}
          disabled={loading}
          onChange={(event) => setSelected(event.target.value)}
          className="mt-1 w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg disabled:opacity-50"
        >
          <option value="">Choose a saved view…</option>
          {views.map((view) => (
            <option key={view.id} value={view.id}>
              {view.is_default ? 'Default · ' : ''}
              {view.name}
              {view.shared ? ' · shared' : ''}
            </option>
          ))}
        </select>
        <p className="mt-1 text-[10px] text-fg-3">
          {loading ? 'Loading views…' : `${views.length} available`}
          {error ? ` · ${error}` : ''}
          {selectedView ? ` · ${savedViewSummary(selectedView)}` : ''}
        </p>
      </div>
      <button
        type="button"
        disabled={!selectedView}
        onClick={() => selectedView && onApply(selectedView)}
        className="rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
      >
        Apply view
      </button>
      <button
        type="button"
        onClick={onManage}
        className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg hover:brightness-110"
      >
        Manage views & segments
      </button>
    </div>
  )
}

// --------------------------------------------------------------------------- //
//  Management surface                                                          //
// --------------------------------------------------------------------------- //

export default function AdminSavedViews({
  onApply,
}: {
  onApply?: (view: AdminSavedView) => void
}) {
  const [catalog, setCatalog] = useState<AdminSavedViewCatalog | null>(null)
  const [fields, setFields] = useState<AdminSegmentFieldsResponse | null>(null)
  const [views, setViews] = useState<AdminSavedView[]>([])
  const [segments, setSegments] = useState<AdminSegment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [savingView, setSavingView] = useState(false)
  const [savingSegment, setSavingSegment] = useState(false)
  const [preview, setPreview] = useState<AdminSegmentPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [segmentPreviews, setSegmentPreviews] = useState<Record<string, AdminSegmentPreview>>({})
  const [draft, setDraft] = useState<AdminSegmentDefinition>({
    match: 'all',
    conditions: [{ ...DRAFT_CONDITION }],
  })
  const [groupBy, setGroupBy] = useState<'plan' | 'role' | 'verified' | ''>('plan')
  const [segmentName, setSegmentName] = useState('')
  const [segmentDescription, setSegmentDescription] = useState('')
  const [segmentShared, setSegmentShared] = useState(false)

  const [viewName, setViewName] = useState('')
  const [viewScope, setViewScope] = useState<AdminSavedViewScope>('analytics')
  const [viewRange, setViewRange] = useState('30')
  const [viewShared, setViewShared] = useState(false)
  const [viewDefault, setViewDefault] = useState(false)
  const [viewFilterRows, setViewFilterRows] = useState<Array<{ key: string; value: string }>>([
    { key: 'plan', value: 'pro' },
  ])
  const [viewColumns, setViewColumns] = useState<string[]>([])
  const [viewSortField, setViewSortField] = useState('')
  const [viewSortDirection, setViewSortDirection] = useState<'asc' | 'desc'>('desc')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextCatalog, nextFields, nextViews, nextSegments] = await Promise.all([
        apiClient.getAdminSavedViewCatalog(),
        apiClient.getAdminSegmentFields(),
        apiClient.getAdminSavedViews({ limit: 100 }),
        apiClient.getAdminSegments({ limit: 100 }),
      ])
      setCatalog(nextCatalog)
      setFields(nextFields)
      setViews(nextViews.items)
      setSegments(nextSegments.items)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const scopeCatalog: AdminSavedViewScopeCatalogEntry | undefined = useMemo(
    () => catalog?.scopes.find((entry) => entry.scope === viewScope),
    [catalog, viewScope],
  )

  useEffect(() => {
    // A new scope has a different allowlist; reset dependent draft fields
    // instead of sending analytics filters to the operations endpoint.
    if (!scopeCatalog) return
    setViewFilterRows((rows) =>
      rows.filter((row) => scopeCatalog.filters.includes(row.key)),
    )
    setViewColumns((columns) => columns.filter((column) => scopeCatalog.columns.includes(column)))
    setViewSortField((field) => (scopeCatalog.sort_fields.includes(field) ? field : ''))
  }, [scopeCatalog])

  const refresh = () => setRefreshKey((value) => value + 1)

  const handleError = (err: unknown, context: string) => {
    if (isConflict(err)) {
      toast.error(`${context} changed elsewhere. Reloading the latest version.`)
      refresh()
      return
    }
    toast.error(errorMessage(err))
  }

  const saveView = async (event: React.FormEvent) => {
    event.preventDefault()
    if (savingView) return
    setSavingView(true)
    try {
      const sort = viewSortField
        ? { field: viewSortField, direction: viewSortDirection }
        : null
      const created = await apiClient.createAdminSavedView({
        name: viewName.trim(),
        scope: viewScope,
        filters: filtersFromRows(viewFilterRows),
        columns: viewColumns,
        sort,
        range_days: viewRange ? Number(viewRange) : null,
        shared: viewShared,
        is_default: viewDefault,
      })
      toast.success(`Saved view “${created.name}”`)
      setViewName('')
      setViewDefault(false)
      refresh()
      onApply?.(created)
    } catch (err) {
      handleError(err, 'Saved view')
    } finally {
      setSavingView(false)
    }
  }

  const renameView = async (view: AdminSavedView) => {
    const name = window.prompt('New view name', view.name)
    if (!name || name.trim() === view.name) return
    try {
      await apiClient.updateAdminSavedView(view.id, {
        expected_version: view.version,
        name: name.trim(),
      })
      toast.success('View renamed')
      refresh()
    } catch (err) {
      handleError(err, 'Saved view')
    }
  }

  const toggleViewShared = async (view: AdminSavedView) => {
    try {
      await apiClient.updateAdminSavedView(view.id, {
        expected_version: view.version,
        shared: !view.shared,
      })
      toast.success(view.shared ? 'View is private again' : 'View shared with admins')
      refresh()
    } catch (err) {
      handleError(err, 'Saved view')
    }
  }

  const makeViewDefault = async (view: AdminSavedView) => {
    try {
      await apiClient.updateAdminSavedView(view.id, {
        expected_version: view.version,
        is_default: true,
      })
      toast.success('Default view updated')
      refresh()
    } catch (err) {
      handleError(err, 'Saved view')
    }
  }

  const deleteView = async (view: AdminSavedView) => {
    const reason = window.prompt(`Reason for deleting “${view.name}” (audited)`)
    if (!reason || reason.trim().length < 3) return
    if (!window.confirm(`Delete “${view.name}”? The row is soft-deleted and audited.`)) return
    try {
      await apiClient.deleteAdminSavedView(view.id, view.version, reason.trim())
      toast.success('View deleted')
      refresh()
    } catch (err) {
      handleError(err, 'Saved view')
    }
  }

  const addFilterRow = () => {
    const available = scopeCatalog?.filters.find(
      (key) => !viewFilterRows.some((row) => row.key === key),
    )
    setViewFilterRows((rows) => [...rows, { key: available ?? '', value: '' }])
  }

  const runPreview = async () => {
    if (previewing) return
    setPreviewing(true)
    setPreviewError(null)
    try {
      const result = await apiClient.previewAdminSegment(
        draft,
        groupBy || null,
      )
      setPreview(result)
    } catch (err) {
      setPreview(null)
      setPreviewError(errorMessage(err))
    } finally {
      setPreviewing(false)
    }
  }

  const saveSegment = async (event: React.FormEvent) => {
    event.preventDefault()
    if (savingSegment) return
    setSavingSegment(true)
    try {
      const created = await apiClient.createAdminSegment({
        name: segmentName.trim(),
        description: segmentDescription.trim() || null,
        definition: draft,
        shared: segmentShared,
      })
      toast.success(`Segment “${created.name}” saved`)
      setSegmentName('')
      setSegmentDescription('')
      setSegmentShared(false)
      refresh()
    } catch (err) {
      handleError(err, 'Segment')
    } finally {
      setSavingSegment(false)
    }
  }

  const previewSaved = async (segment: AdminSegment) => {
    try {
      const result = await apiClient.previewSavedAdminSegment(
        segment.id,
        groupBy || null,
      )
      setSegmentPreviews((current) => ({ ...current, [segment.id]: result }))
    } catch (err) {
      handleError(err, 'Segment')
    }
  }

  const toggleSegmentShared = async (segment: AdminSegment) => {
    try {
      await apiClient.updateAdminSegment(segment.id, {
        expected_version: segment.version,
        shared: !segment.shared,
      })
      toast.success(segment.shared ? 'Segment is private again' : 'Segment shared with admins')
      refresh()
    } catch (err) {
      handleError(err, 'Segment')
    }
  }

  const deleteSegment = async (segment: AdminSegment) => {
    const reason = window.prompt(`Reason for deleting “${segment.name}” (audited)`)
    if (!reason || reason.trim().length < 3) return
    if (!window.confirm(`Delete “${segment.name}”?`)) return
    try {
      await apiClient.deleteAdminSegment(segment.id, segment.version, reason.trim())
      toast.success('Segment deleted')
      refresh()
    } catch (err) {
      handleError(err, 'Segment')
    }
  }

  const setCondition = (index: number, patch: Partial<AdminSegmentCondition>) => {
    setDraft((current) => ({
      ...current,
      conditions: current.conditions.map((condition, position) =>
        position === index ? { ...condition, ...patch } : condition,
      ),
    }))
  }

  const addCondition = () => {
    if (!fields || draft.conditions.length >= fields.max_conditions) return
    setDraft((current) => ({
      ...current,
      conditions: [...current.conditions, { ...DRAFT_CONDITION }],
    }))
  }

  const removeCondition = (index: number) => {
    setDraft((current) => ({
      ...current,
      conditions: current.conditions.filter((_, position) => position !== index),
    }))
  }

  if (loading && !catalog) {
    return <p role="status" className="text-sm text-fg-3">Loading saved views and segments…</p>
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-semibold text-fg">Saved views</h2>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
          Save a tab&apos;s name, range, allowlisted filters, columns and sort. Private views are
          owner-only; sharing exposes the definition to other admins but never grants edit rights.
          Every create, rename, share and delete is audited. Names, filters and descriptions are
          rejected when they look like PII, credentials or document content.
        </p>
        {error && (
          <p role="alert" className="mt-2 rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err">
            {error}
          </p>
        )}
      </div>

      <form onSubmit={saveView} className="space-y-4 rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block text-[11px] text-fg-2">
            View name
            <input
              required
              minLength={2}
              maxLength={80}
              value={viewName}
              onChange={(event) => setViewName(event.target.value)}
              placeholder="Growth review"
              className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
            />
          </label>
          <label className="block text-[11px] text-fg-2">
            Tab
            <select
              value={viewScope}
              onChange={(event) => setViewScope(event.target.value as AdminSavedViewScope)}
              className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
            >
              {SCOPES.map((scope) => (
                <option key={scope.id} value={scope.id}>{scope.label}</option>
              ))}
            </select>
          </label>
          <label className="block text-[11px] text-fg-2">
            Range (days)
            <input
              type="number"
              min={1}
              max={365}
              value={viewRange}
              onChange={(event) => setViewRange(event.target.value)}
              className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
            />
          </label>
          <div className="flex items-end gap-3 text-[11px] text-fg-2">
            <label className="inline-flex items-center gap-2">
              <input type="checkbox" checked={viewShared} onChange={(event) => setViewShared(event.target.checked)} />
              Shared
            </label>
            <label className="inline-flex items-center gap-2">
              <input type="checkbox" checked={viewDefault} onChange={(event) => setViewDefault(event.target.checked)} />
              Default
            </label>
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-fg-3">Allowlisted filters</p>
            <button type="button" onClick={addFilterRow} className="text-[11px] font-medium text-accent-strong underline">
              Add filter
            </button>
          </div>
          <div className="mt-2 space-y-2">
            {viewFilterRows.map((row, index) => (
              <div key={`${row.key}:${index}`} className="flex flex-wrap items-center gap-2">
                <select
                  aria-label="Filter key"
                  value={row.key}
                  onChange={(event) => setViewFilterRows((rows) => rows.map((item, position) => position === index ? { ...item, key: event.target.value } : item))}
                  className="rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                >
                  <option value="">Filter…</option>
                  {(scopeCatalog?.filters ?? []).map((key) => <option key={key} value={key}>{key}</option>)}
                </select>
                <input
                  aria-label="Filter value"
                  value={row.value}
                  onChange={(event) => setViewFilterRows((rows) => rows.map((item, position) => position === index ? { ...item, value: event.target.value } : item))}
                  placeholder="value"
                  className="min-w-[140px] flex-1 rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                />
                <button type="button" onClick={() => setViewFilterRows((rows) => rows.filter((_, position) => position !== index))} className="text-[11px] text-fg-3 underline">
                  Remove
                </button>
              </div>
            ))}
            {viewFilterRows.length === 0 && <p className="text-[11px] text-fg-3">No filters. The server accepts only the keys listed for this tab.</p>}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-4 text-[11px] text-fg-2">
          <fieldset>
            <legend className="mb-1 font-semibold uppercase tracking-wider text-fg-3">Columns</legend>
            <div className="flex flex-wrap gap-2">
              {(scopeCatalog?.columns ?? []).map((column) => (
                <label key={column} className="inline-flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={viewColumns.includes(column)}
                    onChange={(event) => setViewColumns((current) => event.target.checked ? [...current, column] : current.filter((item) => item !== column))}
                  />
                  {column}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="block">
            Sort field
            <select
              value={viewSortField}
              onChange={(event) => setViewSortField(event.target.value)}
              className="mt-1 block rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
            >
              <option value="">No sort</option>
              {(scopeCatalog?.sort_fields ?? []).map((field) => <option key={field} value={field}>{field}</option>)}
            </select>
          </label>
          <label className="block">
            Direction
            <select
              value={viewSortDirection}
              onChange={(event) => setViewSortDirection(event.target.value as 'asc' | 'desc')}
              disabled={!viewSortField}
              className="mt-1 block rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg disabled:opacity-50"
            >
              <option value="desc">desc</option>
              <option value="asc">asc</option>
            </select>
          </label>
          <button
            type="submit"
            disabled={savingView || !viewName.trim()}
            className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-40"
          >
            {savingView ? 'Saving…' : 'Save view'}
          </button>
        </div>
      </form>

      <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
        <div className="border-b border-line px-4 py-3">
          <p className="text-sm font-semibold text-fg">Per-admin and shared views</p>
          <p className="mt-0.5 text-[11px] text-fg-3">
            Defaults apply per tab. Renames and sharing require the owner&apos;s current version;
            concurrent edits return 409 and reload the latest definition.
          </p>
        </div>
        {views.length === 0 ? (
          <p className="px-4 py-6 text-xs text-fg-3">No saved views yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {views.map((view) => (
              <li key={view.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm text-fg">
                    {view.name}
                    {view.is_default && <span className="ml-2 rounded bg-accent-soft px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-accent-strong">default</span>}
                    {view.shared && <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-fg-3">shared</span>}
                    {!view.is_owner && <span className="ml-2 text-[9px] uppercase tracking-wide text-fg-3">read-only</span>}
                  </p>
                  <p className="mt-0.5 text-[11px] text-fg-3">{savedViewSummary(view)} · v{view.version}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {onApply && <button type="button" onClick={() => onApply(view)} className="rounded border border-line px-2 py-1 text-[11px] text-fg-2 hover:bg-surface-2">Apply</button>}
                  {view.is_owner && <>
                    <button type="button" onClick={() => void renameView(view)} className="rounded border border-line px-2 py-1 text-[11px] text-fg-2 hover:bg-surface-2">Rename</button>
                    <button type="button" onClick={() => void toggleViewShared(view)} className="rounded border border-line px-2 py-1 text-[11px] text-fg-2 hover:bg-surface-2">{view.shared ? 'Make private' : 'Share'}</button>
                    <button type="button" onClick={() => void makeViewDefault(view)} className="rounded border border-line px-2 py-1 text-[11px] text-fg-2 hover:bg-surface-2">Set default</button>
                    <button type="button" onClick={() => void deleteView(view)} className="rounded border border-err/30 px-2 py-1 text-[11px] text-err hover:bg-err/[0.06]">Delete</button>
                  </>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-line pt-8">
        <h2 className="text-lg font-semibold text-fg">Cohort builder</h2>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
          Segment definitions compile only allowlisted fields and operators. Preview counts are
          aggregate-only; cohorts below five distinct users are suppressed, and small breakdown
          buckets are omitted. No per-user rows, emails, documents or provider payloads are returned.
        </p>

        {fields && (
          <form onSubmit={saveSegment} className="mt-4 space-y-4 rounded-[var(--radius-lg)] border border-line bg-surface p-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="block text-[11px] text-fg-2">
                Segment name
                <input
                  required
                  minLength={2}
                  maxLength={80}
                  value={segmentName}
                  onChange={(event) => setSegmentName(event.target.value)}
                  placeholder="Pro users who compiled"
                  className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                />
              </label>
              <label className="block text-[11px] text-fg-2">
                Description
                <input
                  maxLength={280}
                  value={segmentDescription}
                  onChange={(event) => setSegmentDescription(event.target.value)}
                  placeholder="Why this cohort exists"
                  className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                />
              </label>
              <label className="block text-[11px] text-fg-2">
                Match
                <select
                  value={draft.match}
                  onChange={(event) => setDraft((current) => ({ ...current, match: event.target.value as 'all' | 'any' }))}
                  className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                >
                  <option value="all">All conditions</option>
                  <option value="any">Any condition</option>
                </select>
              </label>
              <div className="flex items-end gap-3 text-[11px] text-fg-2">
                <label className="inline-flex items-center gap-2">
                  <input type="checkbox" checked={segmentShared} onChange={(event) => setSegmentShared(event.target.checked)} />
                  Shared with admins
                </label>
              </div>
            </div>

            <div className="space-y-2">
              {draft.conditions.map((condition, index) => {
                const field = fields.fields.find((item) => item.field === condition.field)
                return (
                  <div key={index} className="flex flex-wrap items-end gap-2">
                    <label className="text-[11px] text-fg-2">
                      Field
                      <select
                        aria-label={`Segment condition ${index + 1} field`}
                        value={condition.field}
                        onChange={(event) => {
                          const nextField = fields.fields.find((item) => item.field === event.target.value)
                          setCondition(index, {
                            field: event.target.value,
                            operator: nextField?.operators[0] ?? 'eq',
                            value: nextField?.type === 'boolean' ? true : '',
                          })
                        }}
                        className="mt-1 block rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                      >
                        {fields.fields.map((item) => <option key={item.field} value={item.field}>{item.label}</option>)}
                      </select>
                    </label>
                    <label className="text-[11px] text-fg-2">
                      Operator
                      <select
                        aria-label={`Segment condition ${index + 1} operator`}
                        value={condition.operator}
                        onChange={(event) => setCondition(index, { operator: event.target.value })}
                        className="mt-1 block rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                      >
                        {(field?.operators ?? ['eq']).map((operator) => <option key={operator} value={operator}>{operator}</option>)}
                      </select>
                    </label>
                    <label className="min-w-[180px] flex-1 text-[11px] text-fg-2">
                      Value
                      {field?.type === 'boolean' ? (
                        <select
                          aria-label={`Segment condition ${index + 1} value`}
                          value={String(condition.value) === 'true' ? 'true' : 'false'}
                          onChange={(event) => setCondition(index, { value: event.target.value === 'true' })}
                          className="mt-1 block w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                        >
                          <option value="true">true</option>
                          <option value="false">false</option>
                        </select>
                      ) : field?.values ? (
                        <select
                          aria-label={`Segment condition ${index + 1} value`}
                          value={String(condition.value)}
                          onChange={(event) => setCondition(index, { value: event.target.value })}
                          className="mt-1 block w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                        >
                          {field.values.map((value) => <option key={value} value={value}>{value}</option>)}
                        </select>
                      ) : (
                        <input
                          aria-label={`Segment condition ${index + 1} value`}
                          value={formatValue(condition.value)}
                          onChange={(event) => setCondition(index, { value: conditionValue(field, condition.operator, event.target.value) })}
                          placeholder={condition.operator === 'in' || condition.operator === 'not_in' ? 'comma-separated values' : 'value'}
                          className="mt-1 block w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                        />
                      )}
                    </label>
                    <button type="button" onClick={() => removeCondition(index)} disabled={draft.conditions.length === 1} className="rounded border border-line px-2 py-1.5 text-[11px] text-fg-3 disabled:opacity-40">
                      Remove
                    </button>
                  </div>
                )
              })}
            </div>

            <div className="flex flex-wrap items-end gap-3">
              <button type="button" onClick={addCondition} disabled={draft.conditions.length >= fields.max_conditions} className="rounded border border-line px-3 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">
                Add condition
              </button>
              <label className="text-[11px] text-fg-2">
                Group preview by
                <select
                  value={groupBy}
                  onChange={(event) => setGroupBy(event.target.value as 'plan' | 'role' | 'verified' | '')}
                  className="ml-2 rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                >
                  <option value="">Total only</option>
                  {fields.group_by.map((field) => <option key={field} value={field}>{field}</option>)}
                </select>
              </label>
              <button type="button" onClick={() => void runPreview()} disabled={previewing} className="rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">
                {previewing ? 'Previewing…' : 'Preview count'}
              </button>
              <button type="submit" disabled={savingSegment || !segmentName.trim()} className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-40">
                {savingSegment ? 'Saving…' : 'Save segment'}
              </button>
            </div>

            <p className="text-[10px] text-fg-3">
              {fields.minimum_cohort} distinct users are required before a count or breakdown is shown.
              Nothing here can execute SQL: every field and operator is compiled by the server.
            </p>
            {previewError && <p role="alert" className="rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err">{previewError}</p>}
            {preview && <PreviewPanel preview={preview} />}
          </form>
        )}

        <div className="mt-4 overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
          <div className="border-b border-line px-4 py-3">
            <p className="text-sm font-semibold text-fg">Saved segments</p>
            <p className="mt-0.5 text-[11px] text-fg-3">Private by default. Shared segments are readable by every admin and editable only by their owner.</p>
          </div>
          {segments.length === 0 ? (
            <p className="px-4 py-6 text-xs text-fg-3">No segments yet.</p>
          ) : (
            <ul className="divide-y divide-line">
              {segments.map((segment) => {
                const savedPreview = segmentPreviews[segment.id]
                return (
                  <li key={segment.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm text-fg">
                          {segment.name}
                          {segment.shared && <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-fg-3">shared</span>}
                          {!segment.is_owner && <span className="ml-2 text-[9px] uppercase tracking-wide text-fg-3">read-only</span>}
                        </p>
                        <p className="mt-0.5 text-[11px] text-fg-3">
                          {segment.description || 'No description'} · {segment.condition_count} condition{segment.condition_count === 1 ? '' : 's'} · {segment.match} · v{segment.version}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button type="button" onClick={() => void previewSaved(segment)} className="rounded border border-line px-2 py-1 text-[11px] text-fg-2 hover:bg-surface-2">Preview</button>
                        {segment.is_owner && <>
                          <button type="button" onClick={() => void toggleSegmentShared(segment)} className="rounded border border-line px-2 py-1 text-[11px] text-fg-2 hover:bg-surface-2">{segment.shared ? 'Make private' : 'Share'}</button>
                          <button type="button" onClick={() => void deleteSegment(segment)} className="rounded border border-err/30 px-2 py-1 text-[11px] text-err hover:bg-err/[0.06]">Delete</button>
                        </>}
                      </div>
                    </div>
                    {savedPreview && <div className="mt-2"><PreviewPanel preview={savedPreview} compact /></div>}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function PreviewPanel({ preview, compact = false }: { preview: AdminSegmentPreview; compact?: boolean }) {
  return (
    <div className={`rounded-[var(--radius-md)] border border-line bg-bg/50 px-3 py-2 ${compact ? '' : 'mt-1'}`}>
      {preview.suppressed ? (
        <p className="text-xs text-warn">
          Suppressed: fewer than {preview.minimum_cohort} distinct users match. The count is hidden
          to protect small cohorts.
        </p>
      ) : (
        <p className="text-xs text-fg-2">
          <span className="text-lg font-semibold tabular-nums text-fg">{preview.count}</span> distinct users
          {preview.group_by ? ` · grouped by ${preview.group_by}` : ''}
        </p>
      )}
      {preview.groups.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2">
          {preview.groups.map((group: AdminSegmentPreviewGroup) => (
            <li key={group.value} className="rounded-full border border-line bg-surface px-2 py-0.5 text-[10px] text-fg-2">
              {group.value}: <span className="font-semibold tabular-nums">{group.count}</span>
            </li>
          ))}
        </ul>
      )}
      {preview.suppressed_groups > 0 && (
        <p className="mt-1 text-[10px] text-fg-3">
          {preview.suppressed_groups} breakdown bucket{preview.suppressed_groups === 1 ? '' : 's'} hidden under the five-user rule.
        </p>
      )}
    </div>
  )
}
