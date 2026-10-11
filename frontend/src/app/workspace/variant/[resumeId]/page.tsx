'use client'

import { useEntitlements } from '@/contexts/EntitlementsContext'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, Loader2, Save } from 'lucide-react'
import { toast } from 'sonner'

import BuilderPreview from '@/components/builder/BuilderPreview'
import ExportDropdown from '@/components/ExportDropdown'
import LoadingSpinner from '@/components/LoadingSpinner'
import SessionLoadError from '@/components/SessionLoadError'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import {
  apiClient,
  type StructuredResume,
  type VariantVisibility,
  type VariantVisibilityResponse,
} from '@/lib/api-client'

const SECTIONS = [
  ['summary', 'Profile & Summary'],
  ['experience', 'Experience'],
  ['education', 'Education'],
  ['skills', 'Skills'],
  ['projects', 'Projects'],
  ['certifications', 'Certifications'],
  ['awards', 'Awards'],
  ['languages', 'Languages'],
  ['interests', 'Interests'],
] as const

type SectionKey = (typeof SECTIONS)[number][0]
type EntryOption = { id: string; label: string; listItems: string[] }

function entryOptions(source: StructuredResume, section: SectionKey): EntryOption[] {
  switch (section) {
    case 'experience':
      return source.experience.map((item) => ({
        id: item.id, label: [item.title, item.company].filter(Boolean).join(' — ') || 'Untitled role',
        listItems: item.bullets,
      }))
    case 'education':
      return source.education.map((item) => ({
        id: item.id, label: [item.degree, item.institution].filter(Boolean).join(' — ') || 'Untitled education',
        listItems: item.highlights,
      }))
    case 'skills':
      return source.skills.map((item) => ({ id: item.id, label: item.name || 'Untitled skill group', listItems: item.keywords }))
    case 'projects':
      return source.projects.map((item) => ({ id: item.id, label: item.name || 'Untitled project', listItems: item.bullets }))
    case 'certifications':
      return source.certifications.map((item) => ({ id: item.id, label: item.name || 'Untitled certification', listItems: [] }))
    case 'awards':
      return source.awards.map((item) => ({ id: item.id, label: item.name || 'Untitled award', listItems: [] }))
    case 'languages':
      return source.languages.map((item) => ({ id: item.id, label: item.name || 'Untitled language', listItems: [] }))
    case 'interests':
      return source.interests.map((item) => ({ id: item.id, label: item.name || 'Untitled interest', listItems: [] }))
    default:
      return []
  }
}

function cloneVisibility(value: VariantVisibility): VariantVisibility {
  return JSON.parse(JSON.stringify(value)) as VariantVisibility
}

export default function LinkedVariantPage() {
  const { can } = useEntitlements()
  const { resumeId } = useParams<{ resumeId: string }>()
  const { session, isPending, error: sessionError } = useRequireAuth()
  const [data, setData] = useState<VariantVisibilityResponse | null>(null)
  const [visibility, setVisibility] = useState<VariantVisibility | null>(null)
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [reload, setReload] = useState(0)
  const [dirty, setDirty] = useState(false)
  const editRevision = useRef(0)
  const loadGeneration = useRef(0)
  const loadedOwnerEpochRef = useRef<number | null>(null)
  const ownerId = session?.user?.id ?? null
  const ownerEpochRef = useRef<{ ownerId: string | null; resumeId: string; epoch: number }>({ ownerId, resumeId, epoch: 0 })
  if (ownerEpochRef.current.ownerId !== ownerId || ownerEpochRef.current.resumeId !== resumeId) {
    ownerEpochRef.current = {
      ownerId,
      resumeId,
      epoch: ownerEpochRef.current.epoch + 1,
    }
  }
  const ownerEpoch = ownerEpochRef.current.epoch
  const renderOwnerId = ownerId
  const renderResumeId = resumeId
  const renderOwnerEpoch = ownerEpoch
  const mountedRef = useRef(false)
  const saveRequestRef = useRef(0)
  const activeSaveRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      saveRequestRef.current += 1
    }
  }, [])

  useEffect(() => {
    saveRequestRef.current += 1
    activeSaveRef.current = false
    setSaving(false)
  }, [ownerEpoch, resumeId])

  useEffect(() => {
    const generation = ++loadGeneration.current
    const requestEpoch = ownerEpochRef.current.epoch
    const requestOwnerId = ownerEpochRef.current.ownerId
    const requestResumeId = resumeId
    const isCurrentLoad = () => (
      mountedRef.current &&
      requestOwnerId !== null &&
      loadGeneration.current === generation &&
      ownerEpochRef.current.epoch === requestEpoch &&
      ownerEpochRef.current.ownerId === requestOwnerId &&
      ownerEpochRef.current.resumeId === requestResumeId
    )
    if (isPending) return
    if (requestOwnerId === null) {
      setLoading(false)
      return () => {
        if (loadGeneration.current === generation) loadGeneration.current += 1
      }
    }
    editRevision.current += 1
    setLoading(true)
    setLoadError(null)
    apiClient.getVariantVisibility(resumeId)
      .then((response) => {
        if (!isCurrentLoad()) return
        loadedOwnerEpochRef.current = requestEpoch
        setData(response)
        setVisibility(cloneVisibility(response.visibility))
        setTitle(response.resume.title)
        setDirty(false)
      })
      .catch((reason) => {
        if (isCurrentLoad()) {
          setLoadError(reason instanceof Error ? reason.message : 'Variant could not be loaded')
        }
      })
      .finally(() => {
        if (isCurrentLoad()) setLoading(false)
      })
    return () => {
      if (loadGeneration.current === generation) loadGeneration.current += 1
    }
  }, [isPending, reload, ownerEpoch, resumeId])

  const markEdited = () => {
    editRevision.current += 1
    setDirty(true)
  }

  const toggleSection = (section: SectionKey) => {
    markEdited()
    setVisibility((current) => {
      if (!current) return current
      const next = cloneVisibility(current)
      next.hidden_sections = next.hidden_sections.includes(section)
        ? next.hidden_sections.filter((item) => item !== section)
        : [...next.hidden_sections, section]
      return next
    })
  }

  const toggleEntry = (section: SectionKey, entryId: string) => {
    markEdited()
    setVisibility((current) => {
      if (!current) return current
      const next = cloneVisibility(current)
      const hidden = next.hidden_entries[section] ?? []
      next.hidden_entries[section] = hidden.includes(entryId)
        ? hidden.filter((item) => item !== entryId)
        : [...hidden, entryId]
      return next
    })
  }

  const toggleListItem = (section: SectionKey, entryId: string, index: number, value: string) => {
    markEdited()
    setVisibility((current) => {
      if (!current) return current
      const next = cloneVisibility(current)
      next.hidden_list_items[section] ??= {}
      const hidden = next.hidden_list_items[section][entryId] ?? []
      const selected = hidden.some((item) => item.index === index && item.value === value)
      next.hidden_list_items[section][entryId] = selected
        ? hidden.filter((item) => item.index !== index || item.value !== value)
        : [...hidden, { index, value }]
      return next
    })
  }

  const save = async () => {
    if (
      !mountedRef.current ||
      activeSaveRef.current ||
      !renderOwnerId ||
      renderOwnerEpoch !== ownerEpochRef.current.epoch ||
      renderOwnerId !== ownerEpochRef.current.ownerId ||
      renderResumeId !== ownerEpochRef.current.resumeId ||
      loadedOwnerEpochRef.current !== renderOwnerEpoch ||
      !visibility ||
      !title.trim()
    ) return
    const revision = editRevision.current
    const snapshotTitle = title.trim()
    const snapshotVisibility = cloneVisibility(visibility)
    const requestToken = ++saveRequestRef.current
    const requestEpoch = renderOwnerEpoch
    const requestOwnerId = renderOwnerId
    const requestResumeId = renderResumeId
    activeSaveRef.current = true
    const isCurrentSave = () => (
      mountedRef.current &&
      saveRequestRef.current === requestToken &&
      ownerEpochRef.current.epoch === requestEpoch &&
      ownerEpochRef.current.ownerId === requestOwnerId &&
      ownerEpochRef.current.resumeId === requestResumeId
    )
    setSaving(true)
    try {
      const response = await apiClient.updateVariantVisibility(resumeId, {
        title: snapshotTitle, visibility: snapshotVisibility,
      })
      if (!isCurrentSave()) return
      if (revision === editRevision.current) {
        setData(response)
        setVisibility(cloneVisibility(response.visibility))
        setDirty(false)
        toast.success('Variant visibility saved')
      } else {
        toast.success('Earlier visibility saved; newer edits remain unsaved')
      }
    } catch (reason) {
      if (isCurrentSave()) toast.error(reason instanceof Error ? reason.message : 'Variant could not be saved')
    } finally {
      if (isCurrentSave()) {
        activeSaveRef.current = false
        setSaving(false)
      }
    }
  }

  if (isPending || loading) return <LoadingSpinner />
  if (sessionError && !session) return <SessionLoadError area="Linked variant" />
  if (!session) return null
  if (loadError || !data || !visibility) {
    if (!loadError && loading) return <LoadingSpinner />
    return (
      <div className="content-shell py-16 text-center">
        <h1 className="text-xl font-semibold text-fg">Linked variant could not be loaded</h1>
        <p role="alert" className="mt-2 text-sm text-err">{loadError}</p>
        <button type="button" onClick={() => setReload((value) => value + 1)} className="mt-4 rounded border border-line px-4 py-2 text-sm">Retry</button>
      </div>
    )
  }
  if (loadedOwnerEpochRef.current !== ownerEpoch) return <LoadingSpinner />

  return (
    <div className="content-shell space-y-6 pb-16">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-fg-3">Source-linked variant</p>
          <h1 className="mt-2 text-3xl font-semibold text-fg">Choose what this variant includes</h1>
          <p className="mt-2 text-sm text-fg-2">
            Content stays synced from {can('b08')
              ? <Link className="text-accent-strong underline" href={`/workspace/builder/${data.source_resume_id}`}>{data.source_title}</Link>
              : <span>{data.source_title}</span>}.
            Editing its LaTeX directly will detach this variant from future source updates.
          </p>
        </div>
        <div className="flex gap-2">
          <ExportDropdown resumeId={resumeId} variant="toolbar" />
          <Link href={`/workspace/${resumeId}/edit`} className="rounded border border-line px-3 py-2 text-xs text-fg-2">Advanced editor</Link>
          {dirty && <span role="status" className="self-center text-xs text-warn">Unsaved changes</span>}
          <button type="button" onClick={() => void save()} disabled={saving || !title.trim()} className="inline-flex items-center gap-2 rounded bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-50">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save visibility
          </button>
        </div>
      </header>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_430px]">
        <section className="space-y-4">
          <label className="block text-xs uppercase tracking-[0.14em] text-fg-3" htmlFor="variant-title">Variant title</label>
          <input
            id="variant-title"
            value={title}
            maxLength={255}
            onChange={(event) => {
              markEdited()
              setTitle(event.target.value)
            }}
            className="w-full rounded border border-line bg-surface px-4 py-3 text-fg"
          />
          {SECTIONS.map(([section, label]) => {
            const sectionHidden = visibility.hidden_sections.includes(section)
            const masterHidden = data.source_content.hidden_sections.includes(section)
            const entries = entryOptions(data.source_content, section)
            return (
              <article key={section} className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h2 className="font-semibold text-fg">{label}</h2>
                    {masterHidden && <p className="text-xs text-fg-3">Hidden in the master resume</p>}
                  </div>
                  <button type="button" disabled={masterHidden} aria-pressed={!sectionHidden && !masterHidden} onClick={() => toggleSection(section)} className="inline-flex items-center gap-2 rounded border border-line px-3 py-2 text-xs disabled:opacity-40">
                    {sectionHidden || masterHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    {sectionHidden || masterHidden ? 'Hidden' : 'Visible'}
                  </button>
                </div>
                {!sectionHidden && !masterHidden && entries.length > 0 && (
                  <div className="mt-4 space-y-3 border-t border-line pt-4">
                    {entries.map((entry) => {
                      const entryHidden = (visibility.hidden_entries[section] ?? []).includes(entry.id)
                      return (
                        <div key={entry.id} className="rounded border border-line bg-surface-2 p-3">
                          <label className="flex items-center gap-2 text-sm text-fg">
                            <input type="checkbox" checked={!entryHidden} onChange={() => toggleEntry(section, entry.id)} />
                            {entry.label}
                          </label>
                          {!entryHidden && entry.listItems.length > 0 && (
                            <div className="mt-2 space-y-1 pl-6">
                              {entry.listItems.map((item, index) => {
                                const hidden = (visibility.hidden_list_items[section]?.[entry.id] ?? [])
                                  .some((selector) => selector.index === index && selector.value === item)
                                return (
                                  <label key={`${entry.id}-${index}`} className="flex items-start gap-2 text-xs text-fg-2">
                                    <input type="checkbox" checked={!hidden} onChange={() => toggleListItem(section, entry.id, index, item)} />
                                    <span>{item}</span>
                                  </label>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </article>
            )
          })}
        </section>
        <aside className="xl:sticky xl:top-24 xl:self-start">
          <BuilderPreview
            preview={data.preview}
            title={data.resume.title}
            structured={data.effective_content}
            templateFamily={data.template_family}
            completenessScore={data.metrics.completeness_score}
            pageEstimate={data.metrics.page_estimate}
            warnings={data.metrics.warnings}
          />
          <p className="mt-2 text-center text-xs text-fg-3">Preview reflects the last saved visibility.</p>
        </aside>
      </div>
    </div>
  )
}
