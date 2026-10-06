'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { History, Loader2, RotateCcw, Save } from 'lucide-react'
import {
  apiClient,
  type JobApplication,
  type ResumeElementType,
  type ResumeElementVersion,
} from '@/lib/api-client'

export interface VersionableResumeElement {
  key: string
  label: string
  type: ResumeElementType
  content: string
  section: 'experience' | 'project'
  entryId: string
  bulletId: string
}

interface ElementVersionHistoryPanelProps {
  resumeId: string
  elements: VersionableResumeElement[]
  onRestore: (element: VersionableResumeElement, content: string, expectedCurrentContent: string) => boolean
}

export default function ElementVersionHistoryPanel({ resumeId, elements, onRestore }: ElementVersionHistoryPanelProps) {
  const [selectedKey, setSelectedKey] = useState(elements[0]?.key ?? '')
  const [versions, setVersions] = useState<ResumeElementVersion[]>([])
  const [loading, setLoading] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState<'manual' | 'ai' | 'import'>('manual')
  const [applicationId, setApplicationId] = useState('')
  const [applications, setApplications] = useState<JobApplication[]>([])
  const [applicationsLoading, setApplicationsLoading] = useState(false)
  const [applicationsError, setApplicationsError] = useState<string | null>(null)
  const [applicationsRetry, setApplicationsRetry] = useState(0)
  const [actioningId, setActioningId] = useState<string | null>(null)
  const applicationsRequestGeneration = useRef(0)

  const selected = useMemo(
    () => elements.find(element => element.key === selectedKey) ?? elements[0],
    [elements, selectedKey],
  )
  const selectedKeyRef = useRef(`${resumeId}:${selected?.key ?? ''}`)
  const selectedElementKey = selected?.key ?? ''

  useEffect(() => {
    const identity = `${resumeId}:${selectedElementKey}`
    selectedKeyRef.current = identity
    setSaving(false)
    setActioningId(null)
    if (!selectedElementKey) {
      setVersions([])
      setNextCursor(null)
      return
    }
    setSelectedKey(selectedElementKey)
    let cancelled = false
    setVersions([])
    setNextCursor(null)
    setLoading(true)
    setError(null)
    apiClient.getResumeElementVersions(resumeId, selectedElementKey, { limit: 20 })
      .then(page => { if (!cancelled && selectedKeyRef.current === identity) { setVersions(page.items); setNextCursor(page.next_cursor) } })
      .catch(caught => { if (!cancelled && selectedKeyRef.current === identity) setError(caught instanceof Error ? caught.message : 'History unavailable') })
      .finally(() => { if (!cancelled && selectedKeyRef.current === identity) setLoading(false) })
    return () => { cancelled = true }
  }, [resumeId, selectedElementKey])

  useEffect(() => {
    const generation = ++applicationsRequestGeneration.current
    let cancelled = false
    setApplicationsLoading(true)
    setApplicationsError(null)
    setApplications([])
    apiClient.listApplications()
      .then(result => {
        if (cancelled || generation !== applicationsRequestGeneration.current) return
        const ownResumeApplications = Object.values(result.by_status)
          .flat()
          .filter(application => application.resume_id === resumeId)
        setApplications(ownResumeApplications.slice(0, 100))
      })
      .catch(caught => {
        if (cancelled || generation !== applicationsRequestGeneration.current) return
        setApplications([])
        setApplicationsError(caught instanceof Error ? caught.message : 'Could not load tracker applications')
      })
      .finally(() => {
        if (!cancelled && generation === applicationsRequestGeneration.current) setApplicationsLoading(false)
      })
    return () => {
      cancelled = true
      if (applicationsRequestGeneration.current === generation) applicationsRequestGeneration.current += 1
    }
  }, [applicationsRetry, resumeId])

  const saveSnapshot = async () => {
    if (!selected || !selected.content.trim()) return
    const identity = `${resumeId}:${selected.key}`
    setSaving(true)
    setError(null)
    try {
      const created = await apiClient.createResumeElementVersion(resumeId, {
        element_key: selected.key,
        element_type: selected.type,
        content: selected.content,
        source,
        operation: versions.length ? 'edit' : 'create',
        expected_head_version_id: versions[0]?.id,
        application_id: applicationId.trim() || undefined,
      })
      if (selectedKeyRef.current === identity) {
        setVersions(current => [created, ...current.filter(version => version.id !== created.id)])
      }
    } catch (caught) {
      if (selectedKeyRef.current === identity) setError(caught instanceof Error ? caught.message : 'Could not save snapshot')
    } finally {
      if (selectedKeyRef.current === identity) setSaving(false)
    }
  }

  const actOnVersion = async (version: ResumeElementVersion) => {
    if (!selected || !versions[0]) return
    if (actioningId) return
    const actionIdentity = `${resumeId}:${selected.key}`
    const expectedCurrentContent = selected.content
    setActioningId(version.id)
    setError(null)
    try {
      const created = await apiClient.restoreResumeElementVersion(resumeId, version.id, versions[0].id)
      if (selectedKeyRef.current === actionIdentity) {
        const applied = onRestore(selected, created.content, expectedCurrentContent)
        if (!applied) setError('This bullet changed while the restore was running. Its newer local text was kept.')
        setVersions(current => [created, ...current])
      }
    } catch (caught) {
      if (selectedKeyRef.current === actionIdentity) setError(caught instanceof Error ? caught.message : 'Could not restore version')
    } finally {
      if (selectedKeyRef.current === actionIdentity) setActioningId(null)
    }
  }

  const loadOlder = async () => {
    if (!selected || !nextCursor || loadingOlder) return
    const identity = `${resumeId}:${selected.key}`
    const cursor = nextCursor
    setLoadingOlder(true)
    try {
      const page = await apiClient.getResumeElementVersions(resumeId, selected.key, { limit: 20, cursor })
      if (selectedKeyRef.current !== identity) return
      setVersions(current => {
        const seen = new Set(current.map(version => version.id))
        return [...current, ...page.items.filter(version => !seen.has(version.id))]
      })
      setNextCursor(page.next_cursor)
    } catch (caught) {
      if (selectedKeyRef.current === identity) setError(caught instanceof Error ? caught.message : 'Could not load older versions')
    } finally {
      if (selectedKeyRef.current === identity) setLoadingOlder(false)
    }
  }

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
      <div className="flex items-center gap-2 text-sm font-semibold text-fg">
        <History className="h-4 w-4 text-accent-strong" />
        Element history
      </div>
      <p className="mt-2 text-xs leading-5 text-fg-3">
        Save immutable snapshots of a bullet or other builder element. Restore creates a new snapshot; it never erases history.
      </p>
      {!elements.length ? (
        <p className="mt-4 text-xs text-fg-3">Add an experience or project bullet to start tracking versions.</p>
      ) : (
        <>
          <label className="mt-4 block text-[11px] uppercase tracking-[0.12em] text-fg-3" htmlFor="element-version-select">Element</label>
          <select
            id="element-version-select"
            value={selected?.key ?? ''}
            onChange={event => setSelectedKey(event.target.value)}
            className="mt-2 w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg"
          >
            {elements.map(element => <option key={element.key} value={element.key}>{element.label}</option>)}
          </select>
          <div className="mt-3 flex items-center gap-2">
            <select value={source} onChange={event => setSource(event.target.value as typeof source)} className="rounded-[var(--radius-md)] border border-line bg-bg px-2 py-2 text-xs text-fg">
              <option value="manual">Manual</option><option value="ai">AI-assisted</option><option value="import">Imported</option>
            </select>
            <button type="button" onClick={() => void saveSnapshot()} disabled={saving || loading || !selected?.content.trim()} className="flex items-center gap-1 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs text-accent-fg disabled:opacity-50">
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              Save snapshot
            </button>
          </div>
          <label className="mt-3 block text-[11px] uppercase tracking-[0.12em] text-fg-3" htmlFor="element-version-application">Link tracker evidence (optional)</label>
          <select
            id="element-version-application"
            value={applicationId}
            onChange={event => setApplicationId(event.target.value)}
            disabled={applicationsLoading}
            className="mt-2 w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg disabled:opacity-50"
          >
            <option value="">No application linked</option>
            {applications.map(application => (
              <option key={application.id} value={application.id}>
                {application.company_name} · {application.role_title} · {application.status}
              </option>
            ))}
          </select>
          {applicationsError ? (
            <div role="alert" className="mt-2 flex items-center justify-between gap-2 rounded border border-danger/30 bg-danger/10 p-2 text-[10px] text-danger">
              <span>Tracker applications are unavailable right now.</span>
              <button type="button" onClick={() => setApplicationsRetry(value => value + 1)} className="shrink-0 rounded border border-danger/30 px-2 py-1 font-medium hover:bg-danger/10">Retry</button>
            </div>
          ) : !applicationsLoading && !applications.length && <p className="mt-1 text-[10px] text-fg-3">No tracker applications are linked to this resume.</p>}
          <p className="mt-1 text-[10px] text-fg-3">Tracker status is user-recorded evidence, not proof this version caused an interview.</p>
          <p className="mt-1 text-[10px] text-fg-3">Branch forks remain API-only until a duplicated builder element can be selected and persisted safely.</p>
          {error && <p className="mt-3 rounded border border-danger/30 bg-danger/10 p-2 text-xs text-danger">{error}</p>}
          <div className="mt-4 space-y-2">
            {loading && <Loader2 className="h-4 w-4 animate-spin text-fg-3" />}
            {!loading && !versions.length && <p className="text-xs text-fg-3">No snapshots yet.</p>}
            {versions.map(version => (
              <div key={version.id} className="rounded border border-line-2 bg-surface-2 p-3">
                <div className="flex items-center justify-between gap-2 text-[10px] text-fg-3">
                  <span>{new Date(version.created_at).toLocaleString()} · {version.source}</span>
                  <span>{version.operation}</span>
                </div>
                <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-xs text-fg">{version.content}</p>
                {version.tracker_evidence && <p className="mt-1 text-[10px] text-accent-strong">Tracker: {version.tracker_evidence.status} at {version.tracker_evidence.company_name}</p>}
                <div className="mt-2 flex gap-2">
                  <button type="button" onClick={() => void actOnVersion(version)} disabled={version.id === versions[0]?.id || actioningId !== null} className="flex items-center gap-1 rounded border border-line px-2 py-1 text-[10px] text-fg disabled:opacity-40"><RotateCcw className="h-3 w-3" /> Restore as new</button>
                </div>
              </div>
            ))}
            {nextCursor && <button type="button" onClick={() => void loadOlder()} disabled={loadingOlder} className="w-full rounded border border-line px-2 py-2 text-xs text-fg disabled:opacity-50">{loadingOlder ? 'Loading older…' : 'Load older versions'}</button>}
          </div>
        </>
      )}
    </section>
  )
}
