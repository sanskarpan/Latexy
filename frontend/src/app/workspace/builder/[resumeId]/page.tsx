'use client'

import Link from 'next/link'
import dynamic from 'next/dynamic'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Eye,
  EyeOff,
  FileText,
  LayoutList,
  Plus,
  RefreshCcw,
  Sparkles,
  Target,
  Wand2,
} from 'lucide-react'
import { toast } from 'sonner'

import BuilderPreview from '@/components/builder/BuilderPreview'
import ElementVersionHistoryPanel, { type VersionableResumeElement } from '@/components/ElementVersionHistoryPanel'
import ExportDropdown from '@/components/ExportDropdown'
import SessionLoadError from '@/components/SessionLoadError'
import {
  apiClient,
  type BuilderResumeResponse,
  type BuilderTemplateResponse,
  type StructuredResume,
} from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import { useBuilderPdf } from '@/hooks/useBuilderPdf'
import {
  cloneStructuredResume,
  createBuilderId,
  DEFAULT_STRUCTURED_RESUME,
  deriveBuilderMetrics,
  deriveBuilderPreview,
  applyRestoredBullet,
  reconcileBulletIds,
  safeBuilderIdentity,
} from '@/lib/resume-builder'

const PDFPreview = dynamic(() => import('@/components/PDFPreview'), {
  ssr: false,
  loading: () => <div role="status" className="flex h-full items-center justify-center text-sm text-fg-2">Loading your PDF preview…</div>,
})

type SectionKey = StructuredResume['section_order'][number]

type SectionConfig = {
  key: SectionKey
  title: string
  description: string
  emptyHint: string
}

const SECTION_CONFIG: SectionConfig[] = [
  {
    key: 'summary',
    title: 'Profile & Summary',
    description: 'Lock the headline, contact details, and the first five seconds of the resume.',
    emptyHint: 'Add name, headline, and a short summary to make the preview immediately usable.',
  },
  {
    key: 'experience',
    title: 'Experience',
    description: 'Lead with impact, measurable outcomes, and role progression.',
    emptyHint: 'Add at least one recent role with results-oriented bullets.',
  },
  {
    key: 'education',
    title: 'Education',
    description: 'Capture degree signal, timeline, and any highlights worth keeping.',
    emptyHint: 'Add one education entry, even for experienced resumes.',
  },
  {
    key: 'skills',
    title: 'Skills',
    description: 'Group keywords by capability so ATS and recruiters can skim quickly.',
    emptyHint: 'Create at least one skill group with relevant keywords.',
  },
  {
    key: 'projects',
    title: 'Projects',
    description: 'Use this when shipped work deserves explicit spotlight beyond job bullets.',
    emptyHint: 'Add a project if it meaningfully strengthens the narrative.',
  },
  {
    key: 'certifications',
    title: 'Certifications',
    description: 'Useful for cloud, security, finance, and other trust-heavy roles.',
    emptyHint: 'Skip unless it materially supports the target job.',
  },
  {
    key: 'awards',
    title: 'Awards',
    description: 'Keep only proof points that add signal rather than vanity.',
    emptyHint: 'Optional section for standout recognition.',
  },
  {
    key: 'languages',
    title: 'Languages',
    description: 'List only real working proficiency or market-relevant fluency.',
    emptyHint: 'Useful for global, customer-facing, and multilingual roles.',
  },
  {
    key: 'interests',
    title: 'Interests',
    description: 'Add sparingly when it makes the candidate more memorable or aligned.',
    emptyHint: 'Usually optional. Use only if it helps the story.',
  },
]

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-[var(--radius-lg)] border border-line bg-surface p-4 ${className}`}>{children}</div>
}

function FieldLabel({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-2 block font-ui text-xs uppercase tracking-[0.14em] text-fg-3">
      {children}
    </label>
  )
}

function TextInput(
  props: React.InputHTMLAttributes<HTMLInputElement> & {
    id?: string
  },
) {
  return (
    <input
      {...props}
      className={`w-full rounded-[var(--radius-md)] border border-line bg-bg px-4 py-3 text-fg outline-none transition focus:border-accent focus:ring-accent focus:ring-offset-bg ${props.className ?? ''}`}
    />
  )
}

function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`w-full rounded-[var(--radius-md)] border border-line bg-bg px-4 py-3 text-fg outline-none transition focus:border-accent focus:ring-accent focus:ring-offset-bg ${props.className ?? ''}`}
    />
  )
}

function SectionHeader({
  title,
  sectionKey,
  description,
  order,
  hidden,
  onMove,
  onToggleHidden,
}: {
  title: string
  sectionKey: SectionKey
  description: string
  order: string[]
  hidden: boolean
  onMove: (sectionKey: SectionKey, direction: -1 | 1) => void
  onToggleHidden: (sectionKey: SectionKey) => void
}) {
  const idx = order.indexOf(sectionKey)
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-lg font-semibold text-fg">{title}</p>
        <p className="mt-1 max-w-2xl text-sm text-fg-2">{description}</p>
      </div>
      <div className="flex items-center gap-2">
        <button type="button" aria-label={`Move ${title} up`} title={`Move ${title} up`} onClick={() => onMove(sectionKey, -1)} disabled={idx <= 0} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-2 py-2 text-xs disabled:opacity-30">
          <ArrowUp className="h-3.5 w-3.5" />
        </button>
        <button type="button" aria-label={`Move ${title} down`} title={`Move ${title} down`} onClick={() => onMove(sectionKey, 1)} disabled={idx === -1 || idx >= order.length - 1} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-2 py-2 text-xs disabled:opacity-30">
          <ArrowDown className="h-3.5 w-3.5" />
        </button>
        <button type="button" aria-label={`${hidden ? 'Show' : 'Hide'} ${title}`} aria-pressed={hidden} title={`${hidden ? 'Show' : 'Hide'} ${title}`} onClick={() => onToggleHidden(sectionKey)} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-2 py-2 text-xs">
          {hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        </button>
      </div>
    </div>
  )
}

function StarterChip({
  label,
  onClick,
}: {
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full border border-line bg-surface-2 px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] text-fg-2 transition hover:brightness-110"
    >
      {label}
    </button>
  )
}

function joinComma(value: string[]) {
  return value.join(', ')
}

function splitComma(value: string) {
  return value.split(',').map(item => item.trim()).filter(Boolean)
}

function splitLines(value: string) {
  return value.split('\n').map(item => item.trim()).filter(Boolean)
}

/** Keep unfinished separators in the editing buffer while saving clean lists. */
function ListTextInput({ value, separator, multiline = false, onChange, ...props }: {
  value: string
  separator: 'lines' | 'comma'
  multiline?: boolean
  onChange: (value: string) => void
} & Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, 'value' | 'onChange'>) {
  const [buffer, setBuffer] = useState(value)
  const emittedValue = useRef(value)
  useEffect(() => {
    if (value !== emittedValue.current) {
      emittedValue.current = value
      setBuffer(value)
    }
  }, [value])
  const handleChange = (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const raw = event.target.value
    setBuffer(raw)
    emittedValue.current = separator === 'lines' ? splitLines(raw).join('\n') : joinComma(splitComma(raw))
    onChange(raw)
  }
  if (multiline) return <TextArea {...props} value={buffer} onChange={handleChange} />
  return <TextInput {...props as React.InputHTMLAttributes<HTMLInputElement>} type="text" value={buffer} onChange={handleChange} />
}

function splitLinesWithIds(value: string, existingBullets: string[], existingIds: string[], entryId: string) {
  const bullets = splitLines(value)
  return {
    bullets,
    bullet_ids: reconcileBulletIds(existingBullets, existingIds, bullets, entryId),
  }
}

function sectionCount(structured: StructuredResume, section: SectionKey) {
  switch (section) {
    case 'summary':
      return Number(Boolean(structured.basics.summary.trim() || structured.basics.name.trim() || structured.basics.label.trim()))
    case 'experience':
      return structured.experience.length
    case 'education':
      return structured.education.length
    case 'skills':
      return structured.skills.length
    case 'projects':
      return structured.projects.length
    case 'certifications':
      return structured.certifications.length
    case 'awards':
      return structured.awards.length
    case 'languages':
      return structured.languages.length
    case 'interests':
      return structured.interests.length
  }
}

function sectionReady(structured: StructuredResume, section: SectionKey) {
  switch (section) {
    case 'summary':
      return Boolean(structured.basics.name.trim() && structured.basics.summary.trim())
    case 'experience':
      return structured.experience.some(item => item.title.trim() && item.company.trim() && item.bullets.some(bullet => bullet.trim()))
    case 'education':
      return structured.education.some(item => item.institution.trim() && item.degree.trim())
    case 'skills':
      return structured.skills.some(item => item.name.trim() && item.keywords.length)
    case 'projects':
      return structured.projects.some(item => item.name.trim() && (item.description.trim() || item.bullets.some(bullet => bullet.trim())))
    case 'certifications':
      return structured.certifications.some(item => item.name.trim())
    case 'awards':
      return structured.awards.some(item => item.name.trim())
    case 'languages':
      return structured.languages.some(item => item.name.trim())
    case 'interests':
      return structured.interests.some(item => item.name.trim())
  }
}

export default function BuilderResumePage() {
  const params = useParams<{ resumeId: string }>()
  const resumeId = params.resumeId
  const { session, isPending: sessionLoading, error: sessionError } = useRequireAuth()

  if (sessionLoading && !session) {
    return <div className="content-shell py-16 text-sm text-fg-2">Loading builder…</div>
  }
  if (sessionError && !session) {
    return <SessionLoadError area="Builder resume" />
  }
  if (!session) return null

  // Keep all private editor state scoped to both authenticated owner and
  // document. A late callback from an old owner/document then has no mounted
  // state to mutate, including an A → B → A transition.
  return (
    <BuilderResumeForm
      key={`${session.user.id}:${resumeId}`}
      resumeId={resumeId}
      session={session}
      authUnverified={Boolean(sessionLoading || sessionError)}
    />
  )
}

type BuilderSession = NonNullable<ReturnType<typeof useRequireAuth>['session']>

function BuilderResumeForm({
  resumeId,
  session,
  authUnverified,
}: {
  resumeId: string
  session: BuilderSession
  authUnverified: boolean
}) {
  const ownerId = session.user.id

  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveAttempt, setSaveAttempt] = useState(0)
  const [saveConflict, setSaveConflict] = useState(false)
  const [conflictDraft, setConflictDraft] = useState<{ title: string; template_id: string; structured_content: StructuredResume } | null>(null)
  const [dirty, setDirty] = useState(false)
  const [templates, setTemplates] = useState<BuilderTemplateResponse[]>([])
  const [title, setTitle] = useState('')
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [structured, setStructured] = useState<StructuredResume>(cloneStructuredResume(DEFAULT_STRUCTURED_RESUME))
  const structuredRef = useRef(structured)
  structuredRef.current = structured
  const [templateFamily, setTemplateFamily] = useState('minimal')
  const [builderStatus, setBuilderStatus] = useState<'active' | 'detached'>('active')
  const [activeSection, setActiveSection] = useState<SectionKey>('summary')
  const initialLoad = useRef(true)
  const completedLoadAttempt = useRef<number | null>(null)
  const editRevision = useRef(0)
  const saveRequestId = useRef(0)
  const saveFlightRef = useRef<Promise<BuilderResumeResponse | null> | null>(null)
  const savedVersionRef = useRef(1)
  const savedBuilderRef = useRef<BuilderResumeResponse | null>(null)
  const savedLatexRef = useRef('')
  const dirtyRef = useRef(false)
  const conflictRef = useRef(false)
  const draftRef = useRef({ title, template_id: selectedTemplateId, structured_content: structured })
  draftRef.current = { title, template_id: selectedTemplateId, structured_content: structured }
  const builderStatusRef = useRef(builderStatus)
  builderStatusRef.current = builderStatus
  const sectionRefs = useRef<Partial<Record<SectionKey, HTMLElement | null>>>({})
  const mountedRef = useRef(false)
  const authVerifiedRef = useRef(!authUnverified)
  authVerifiedRef.current = !authUnverified

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const isCurrentRequest = () => mountedRef.current && authVerifiedRef.current

  const liveMetrics = useMemo(() => deriveBuilderMetrics(structured), [structured])
  const livePreview = useMemo(
    () => deriveBuilderPreview(structured, templateFamily),
    [structured, templateFamily],
  )

  const completenessScore = liveMetrics.completeness_score
  const pageEstimate = liveMetrics.page_estimate
  const warnings = liveMetrics.warnings
  const missingSections = liveMetrics.missing_sections

  // Structured entry IDs are persisted by the builder. The slot suffix gives
  // each bullet an explicit, user-visible identity for this builder surface;
  // callers must never use mutable text as the identity.
  const versionableElements = useMemo<VersionableResumeElement[]>(() => [
    ...structured.experience.flatMap(entry => entry.bullets.map((content, index) => {
      const bulletId = entry.bullet_ids?.[index] || `bullet-${index}`
      return {
        key: `experience:${safeBuilderIdentity(entry.id)}:bullet:${bulletId}`,
        label: `${entry.company || entry.title || 'Experience'} · bullet ${index + 1}`,
        type: 'bullet' as const,
        content,
        section: 'experience' as const,
        entryId: entry.id,
        bulletId,
      }
    })),
    ...structured.projects.flatMap(project => project.bullets.map((content, index) => {
      const bulletId = project.bullet_ids?.[index] || `bullet-${index}`
      return {
        key: `project:${safeBuilderIdentity(project.id)}:bullet:${bulletId}`,
        label: `${project.name || 'Project'} · bullet ${index + 1}`,
        type: 'bullet' as const,
        content,
        section: 'project' as const,
        entryId: project.id,
        bulletId,
      }
    })),
  ], [structured.experience, structured.projects])

  const selectedTemplate = useMemo(
    () => templates.find(template => template.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates],
  )

  useEffect(() => {
    if (authUnverified || !isCurrentRequest()) return
    if (completedLoadAttempt.current === loadAttempt) return
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    Promise.all([apiClient.getBuilderResume(resumeId), apiClient.getBuilderTemplates()])
      .then(([builder, availableTemplates]) => {
        if (cancelled || !isCurrentRequest()) return
        setTemplates(availableTemplates)
        setTitle(builder.resume.title)
        setSelectedTemplateId(builder.resume.selected_template_id ?? availableTemplates[0]?.id ?? '')
        setStructured(cloneStructuredResume(builder.resume.structured_content ?? DEFAULT_STRUCTURED_RESUME))
        setTemplateFamily(builder.template_family)
        setBuilderStatus((builder.resume.builder_status ?? 'active') as 'active' | 'detached')
        savedVersionRef.current = builder.resume.structured_version ?? 1
        savedBuilderRef.current = builder
        savedLatexRef.current = builder.resume.latex_content
        dirtyRef.current = false
        conflictRef.current = false
        setSaveConflict(false)
        setDirty(false)
        setSaveError(null)
        completedLoadAttempt.current = loadAttempt
      })
      .catch(error => {
        if (!cancelled && isCurrentRequest()) {
          setLoadError(error instanceof Error ? error.message : 'Failed to load builder resume')
        }
      })
      .finally(() => {
        if (!cancelled && isCurrentRequest()) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [loadAttempt, ownerId, resumeId, authUnverified])

  // All callers share one queue. A second edit waits for the prior write and
  // uses its returned version, preventing an older PATCH from arriving last.
  const flushSave = useCallback(async (): Promise<BuilderResumeResponse | null> => {
    if (saveFlightRef.current) return saveFlightRef.current
    const saveLatest = async () => {
      if (!mountedRef.current || !authVerifiedRef.current) throw new Error('Please wait for your session to be verified.')
      if (conflictRef.current) throw new Error('Reload the saved copy before saving or exporting.')
      if (builderStatusRef.current === 'detached' && dirtyRef.current) throw new Error('Reconnect the builder before saving these changes.')
      setSaving(true)
      try {
        while (dirtyRef.current) {
          const snapshot = draftRef.current
          if (!snapshot.title.trim() || snapshot.title.length > 255) throw new Error(!snapshot.title.trim() ? 'A résumé title is required' : 'Résumé titles must be 255 characters or fewer')
          const revision = editRevision.current
          const updated = await apiClient.updateBuilderResume(resumeId, {
            ...snapshot,
            title: snapshot.title.trim(),
            expected_structured_version: savedVersionRef.current,
          })
          if (!mountedRef.current || !authVerifiedRef.current) throw new Error('Your session changed. Please try again.')
          savedVersionRef.current = updated.resume.structured_version ?? savedVersionRef.current + 1
          savedBuilderRef.current = updated
          savedLatexRef.current = updated.resume.latex_content
          setTemplateFamily(updated.template_family)
          const nextStatus = (updated.resume.builder_status ?? 'active') as 'active' | 'detached'
          builderStatusRef.current = nextStatus
          setBuilderStatus(nextStatus)
          if (revision === editRevision.current) {
            dirtyRef.current = false
            setDirty(false)
            setSaveError(null)
          }
        }
        return savedBuilderRef.current
      } catch (error) {
        if (mountedRef.current && authVerifiedRef.current) {
          const message = error instanceof Error ? error.message : 'Could not save your changes'
          if (message.includes('409')) {
            conflictRef.current = true
            setSaveConflict(true)
            setSaveError('This résumé changed in another tab. Your edits are still here.')
          } else setSaveError(message)
        }
        throw error
      } finally {
        if (mountedRef.current) setSaving(false)
      }
    }
    const flight = saveLatest()
    saveFlightRef.current = flight
    try { return await flight } finally { if (saveFlightRef.current === flight) saveFlightRef.current = null }
  }, [resumeId])

  const isCurrentPdfRequest = useCallback(() => mountedRef.current && authVerifiedRef.current, [])
  const { previewPdf, downloadPdf, pdfUrl, isGenerating, error: pdfError, clearPreview } = useBuilderPdf({
    resumeId,
    prepareResume: flushSave,
    isCurrent: isCurrentPdfRequest,
  })
  useEffect(() => { clearPreview() }, [structured, title, selectedTemplateId, clearPreview])

  useEffect(() => {
    if (initialLoad.current) { initialLoad.current = false; return }
    if (authUnverified || !dirty || builderStatus === 'detached' || saveConflict) return
    const timeout = window.setTimeout(() => { void flushSave().catch(() => {}) }, 600)
    return () => window.clearTimeout(timeout)
  }, [authUnverified, dirty, structured, title, selectedTemplateId, builderStatus, saveConflict, saveAttempt, flushSave])

  useEffect(() => {
    const warnIfDirty = (event: BeforeUnloadEvent) => {
      if (!dirty) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnIfDirty)
    return () => window.removeEventListener('beforeunload', warnIfDirty)
  }, [dirty])

  const mutateStructured = (mutator: (draft: StructuredResume) => void) => {
    setStructured(prev => {
      const next = cloneStructuredResume(prev)
      mutator(next)
      return next
    })
    editRevision.current += 1
    dirtyRef.current = true
    setDirty(true)
    setSaveError(null)
  }

  const restoreVersionableElement = (
    element: VersionableResumeElement,
    content: string,
    expectedCurrentContent: string,
  ) => {
    const currentEntries = element.section === 'experience'
      ? structuredRef.current.experience
      : structuredRef.current.projects
    const currentEntry = currentEntries.find(item => item.id === element.entryId)
    const currentIndex = currentEntry?.bullet_ids.indexOf(element.bulletId) ?? -1
    if (!currentEntry || currentIndex < 0 || currentEntry.bullets[currentIndex] !== expectedCurrentContent) {
      return false
    }
    mutateStructured(draft => {
      applyRestoredBullet(
        draft,
        element.section,
        element.entryId,
        element.bulletId,
        content,
        expectedCurrentContent,
      )
    })
    return true
  }

  const moveSection = (sectionKey: SectionKey, direction: -1 | 1) => {
    mutateStructured(draft => {
      const currentIndex = draft.section_order.indexOf(sectionKey)
      const targetIndex = currentIndex + direction
      if (currentIndex < 0 || targetIndex < 0 || targetIndex >= draft.section_order.length) return
      const [item] = draft.section_order.splice(currentIndex, 1)
      draft.section_order.splice(targetIndex, 0, item)
    })
  }

  const toggleHidden = (sectionKey: SectionKey) => {
    mutateStructured(draft => {
      if (draft.hidden_sections.includes(sectionKey)) {
        draft.hidden_sections = draft.hidden_sections.filter(section => section !== sectionKey)
      } else {
        draft.hidden_sections = [...draft.hidden_sections, sectionKey]
      }
    })
  }

  const forceReattach = async () => {
    if (!isCurrentRequest()) return
    if (!window.confirm('Replace the advanced editor version with the details shown in this builder?')) return
    const revision = editRevision.current
    const requestId = ++saveRequestId.current
    setSaving(true)
    try {
      const updated = await apiClient.updateBuilderResume(resumeId, {
        title,
        template_id: selectedTemplateId,
        structured_content: structured,
        force_reattach: true,
        expected_structured_version: savedVersionRef.current,
        expected_latex_content: savedLatexRef.current,
      })
      if (!isCurrentRequest() || requestId !== saveRequestId.current) return
      setTemplateFamily(updated.template_family)
      savedVersionRef.current = updated.resume.structured_version ?? savedVersionRef.current + 1
      savedBuilderRef.current = updated
      savedLatexRef.current = updated.resume.latex_content
      setBuilderStatus('active')
      if (revision === editRevision.current) {
        setDirty(false)
        dirtyRef.current = false
        setSaveError(null)
      }
      toast.success('Builder reattached and LaTeX overwritten from structured data')
    } catch (error) {
      if (!isCurrentRequest() || requestId !== saveRequestId.current) return
      const message = error instanceof Error ? error.message : 'Failed to reattach builder'
      if (message.includes('409')) {
        conflictRef.current = true
        setSaveConflict(true)
      }
      setSaveError(message)
      toast.error(message)
    } finally {
      if (mountedRef.current && requestId === saveRequestId.current) setSaving(false)
    }
  }

  const jumpToSection = (section: SectionKey) => {
    setActiveSection(section)
    sectionRefs.current[section]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const healthTone = completenessScore >= 85
    ? 'border-ok/20 bg-ok/10 text-ok'
    : completenessScore >= 65
      ? 'border-warn/20 bg-warn/10 text-warn'
      : 'border-err/20 bg-err/10 text-err'

  if (loading) {
    return <div className="content-shell py-16 text-sm text-fg-2">Loading builder…</div>
  }

  if (loadError) {
    return (
      <div className="content-shell py-16">
        <div role="alert" className="mx-auto max-w-lg rounded-[var(--radius-lg)] border border-err/20 bg-err/10 p-6 text-center">
          <h1 className="text-lg font-semibold text-fg">Builder resume could not be loaded</h1>
          <p className="mt-2 text-sm text-fg-2">{loadError}</p>
          <div className="mt-5 flex justify-center gap-2">
            <Link href="/workspace" className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-sm text-fg-2">Back to workspace</Link>
            <button type="button" onClick={() => setLoadAttempt(value => value + 1)} className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-medium text-accent-fg">Retry</button>
          </div>
        </div>
      </div>
    )
  }

  if (!session) return null

  const hidden = new Set(structured.hidden_sections)
  const missingSet = new Set(missingSections)

  return (
    <div className="content-shell space-y-8 pb-16">
      <header className="flex flex-wrap items-end justify-between gap-4 pt-2">
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Guided Builder</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">{title || 'Untitled Resume'}</h1>
          <p className="mt-2 max-w-3xl text-sm text-fg-2">
            Fill in your details, organize your sections, and download a résumé ready to share.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => { void previewPdf().catch(() => {}) }} disabled={isGenerating || loading || authUnverified || saveConflict || builderStatus === 'detached'} className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg disabled:opacity-50">
            {isGenerating ? 'Preparing PDF…' : 'Preview PDF'}
          </button>
          <ExportDropdown resumeId={resumeId} variant="toolbar" onPdfExport={downloadPdf} beforeExport={async format => {
            await flushSave()
            if (['svg', 'jpeg', 'email', 'google_drive'].includes(format)) await previewPdf()
          }} />
          <Link href={`/workspace/${resumeId}/edit`} onClick={event => {
            if (dirty && !window.confirm('Changes have not been saved. Open the advanced editor anyway?')) event.preventDefault()
          }} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
            Open Advanced Editor
          </Link>
          {saveError && !saveConflict ? (
            <button type="button" aria-live="polite" onClick={() => setSaveAttempt(value => value + 1)} className="rounded-full border border-err/30 bg-err/10 px-3 py-2 text-xs text-err" title={saveError}>
              Save failed · Retry
            </button>
          ) : (
            <div aria-live="polite" className="rounded-full border border-line px-3 py-2 text-xs text-fg-2">
              {saving ? 'Saving…' : dirty ? 'Unsaved changes' : 'All changes saved'}
            </div>
          )}
        </div>
      </header>

      {pdfError && <section role="alert" className="rounded-[var(--radius-lg)] border border-err/30 bg-err/10 p-5">
        <p className="text-sm text-err">{pdfError}</p>
        <button type="button" onClick={() => { void previewPdf().catch(() => {}) }} disabled={isGenerating} className="mt-3 text-sm font-semibold text-fg underline">Try PDF preview again</button>
      </section>}
      {pdfUrl && <section aria-label="Final PDF preview" className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div><h2 className="text-lg font-semibold text-fg">Your PDF is ready</h2><p className="mt-1 text-sm text-fg-2">This is the layout that will appear in your downloaded résumé.</p><p className="mt-1 break-words text-xs text-fg-3">{title || 'resume'}.pdf</p></div>
          <button type="button" onClick={() => { void downloadPdf().catch(() => {}) }} disabled={isGenerating || dirty} className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg disabled:opacity-50">Download PDF</button>
        </div>
        <div data-testid="builder-pdf-preview" className="h-[min(72vh,800px)] min-h-[360px] w-full min-w-0 overflow-hidden rounded-[var(--radius-md)] border border-line">
          <PDFPreview pdfUrl={pdfUrl} isLoading={isGenerating} onDownload={() => { void downloadPdf().catch(() => {}) }} />
        </div>
      </section>}

      {saveConflict && <section role="alert" className="rounded-[var(--radius-lg)] border border-warn/30 bg-warn/10 p-5">
        <p className="font-semibold text-fg">This résumé changed in another tab</p>
        <p className="mt-2 text-sm text-fg-2">Your edits are preserved here. Reload the saved copy to review the changes before saving or exporting.</p>
        <button type="button" disabled={saving} onClick={() => {
          setConflictDraft({ ...draftRef.current, structured_content: cloneStructuredResume(draftRef.current.structured_content) })
          setLoadAttempt(value => value + 1)
        }} className="mt-3 rounded-[var(--radius-md)] border border-line px-4 py-2 text-sm text-fg">Reload saved copy</button>
      </section>}
      {!saveConflict && conflictDraft && <section role="status" className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <p className="text-sm text-fg-2">The latest saved copy is shown. Your previous unsaved draft is still available.</p>
        <button type="button" onClick={() => {
          setTitle(conflictDraft.title)
          setSelectedTemplateId(conflictDraft.template_id)
          setStructured(cloneStructuredResume(conflictDraft.structured_content))
          editRevision.current += 1
          dirtyRef.current = true
          setDirty(true)
          setConflictDraft(null)
        }} className="mt-3 rounded-[var(--radius-md)] border border-line px-4 py-2 text-sm text-fg">Use my previous draft</button>
        <button type="button" onClick={() => setConflictDraft(null)} className="ml-3 text-sm text-fg-2 underline">Keep saved copy</button>
      </section>}

      {builderStatus === 'detached' ? (
        <section className="rounded-[var(--radius-lg)] border border-warn/20 bg-warn/10 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-warn">Builder detached</p>
              <p className="mt-1 text-sm text-warn/80">
                This resume was edited directly in the advanced editor. Structured changes are paused until you explicitly
                overwrite the current LaTeX from builder data.
              </p>
            </div>
            <button type="button" onClick={() => void forceReattach()} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
              <RefreshCcw className="mr-2 inline h-3.5 w-3.5" />
              Reattach Builder
            </button>
          </div>
        </section>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-4">
        <Card className={healthTone}>
          <p className="text-xs uppercase tracking-[0.14em] opacity-70">Résumé completeness</p>
          <p className="mt-2 text-3xl font-semibold">{completenessScore}%</p>
          <p className="mt-2 text-sm opacity-85">
            {missingSections.length
              ? `${missingSections.length} key area${missingSections.length === 1 ? '' : 's'} still weak or missing.`
              : 'Core sections are covered and preview-ready.'}
          </p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Estimated pages</p>
          <p className="mt-2 text-3xl font-semibold text-fg">{pageEstimate}</p>
          <p className="mt-2 text-sm text-fg-2">
            {pageEstimate > 1 ? 'Trim bullets and optional sections to stay tighter.' : 'Compact enough for the most common one-page target.'}
          </p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Sections included</p>
          <p className="mt-2 text-3xl font-semibold text-fg">{livePreview.sections.length}</p>
          <p className="mt-2 text-sm text-fg-2">
            {structured.hidden_sections.length
              ? `${structured.hidden_sections.length} section${structured.hidden_sections.length === 1 ? '' : 's'} hidden from the rendered resume.`
              : 'Empty sections are left out of your résumé.'}
          </p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Current Template</p>
          <p className="mt-2 text-lg font-semibold text-fg">{selectedTemplate?.name || 'Template'}</p>
          <p className="mt-2 text-sm text-fg-2">
            {selectedTemplate?.category_label || 'Résumé template'}
          </p>
        </Card>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px] 2xl:grid-cols-[240px_minmax(0,1fr)_420px]">
        <aside className="space-y-4 xl:col-span-2 2xl:col-span-1">
          <Card className="2xl:sticky 2xl:top-24">
            <div className="flex items-center gap-2 text-sm font-semibold text-fg">
              <LayoutList className="h-4 w-4 text-accent-strong" />
              Your sections
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-3 2xl:grid-cols-1">
              {SECTION_CONFIG.map(section => {
                const count = sectionCount(structured, section.key)
                const ready = sectionReady(structured, section.key)
                const isActive = activeSection === section.key
                return (
                  <button
                    key={section.key}
                    type="button"
                    onClick={() => jumpToSection(section.key)}
                    className={`w-full rounded-[var(--radius-lg)] border px-3 py-3 text-left transition ${
                      isActive
                        ? 'border-accent bg-accent-soft'
                        : 'border-line bg-surface hover:bg-surface-2'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-fg">{section.title}</p>
                      {ready ? <CheckCircle2 className="h-4 w-4 text-ok" /> : null}
                    </div>
                    <p className="mt-1 text-xs text-fg-3">
                      {hidden.has(section.key)
                        ? 'Hidden from output'
                        : count
                          ? `${count} item${count === 1 ? '' : 's'} configured`
                          : section.emptyHint}
                    </p>
                  </button>
                )
              })}
            </div>

            {missingSections.length ? (
              <div className="mt-5 rounded-[var(--radius-lg)] border border-warn/20 bg-warn/10 px-3 py-3">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-warn">
                  <Target className="h-3.5 w-3.5" />
                  Next fixes
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {missingSections.map(item => {
                    const key = item === 'name' || item === 'email' ? 'summary' : item
                    if (!SECTION_CONFIG.some(section => section.key === key)) return null
                    return (
                      <StarterChip key={item} label={item.replace('_', ' ')} onClick={() => jumpToSection(key as SectionKey)} />
                    )
                  })}
                </div>
              </div>
            ) : null}
          </Card>
        </aside>

        <div className="space-y-6">
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
            <div className="grid gap-4">
              <div className="grid gap-4">
                <div>
                  <FieldLabel htmlFor="builder-resume-title">Resume Title</FieldLabel>
                  <TextInput
                    id="builder-resume-title"
                    type="text"
                    value={title}
                    maxLength={255}
                    onChange={event => {
                      setTitle(event.target.value)
                      editRevision.current += 1
                      dirtyRef.current = true
                      setDirty(true)
                      setSaveError(null)
                    }}
                  />
                </div>
                <div>
                  <FieldLabel htmlFor="builder-template-select">Template</FieldLabel>
                  <select
                    id="builder-template-select"
                    value={selectedTemplateId}
                    onChange={event => {
                      setSelectedTemplateId(event.target.value)
                      editRevision.current += 1
                      dirtyRef.current = true
                      setDirty(true)
                      setSaveError(null)
                    }}
                    className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-4 py-3 text-fg outline-none transition focus:border-accent focus:ring-accent focus:ring-offset-bg"
                  >
                    {templates.map(template => (
                      <option key={template.id} value={template.id}>
                        {template.name} · {template.category_label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <Card className="flex h-full flex-col justify-between">
                <div className="flex items-center gap-2 text-sm font-semibold text-fg">
                  <Wand2 className="h-4 w-4 text-accent-strong" />
                  Writing tips
                </div>
                <div className="mt-3 space-y-2 text-sm text-fg-2">
                  <p>Lead with measurable impact, not responsibility lists.</p>
                  <p>Keep the preview one page unless the role clearly benefits from a second page.</p>
                  <p>Hide sections that don’t reinforce the target job instead of filling them with weak content.</p>
                </div>
              </Card>
            </div>

            {warnings.length ? (
              <div className="mt-4 space-y-2">
                {warnings.map(warning => (
                  <div key={warning} className="rounded-[var(--radius-md)] border border-warn/20 bg-warn/10 px-3 py-2 text-xs text-warn">
                    {warning}
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          <section
            ref={node => {
              sectionRefs.current.summary = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Profile & Summary"
              sectionKey="summary"
              description="Control the resume header, role headline, and the core narrative recruiters see first."
              order={structured.section_order}
              hidden={hidden.has('summary')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="grid gap-4 md:grid-cols-2">
              {[
                ['Full Name', 'name'],
                ['Headline', 'label'],
                ['Email', 'email'],
                ['Phone', 'phone'],
                ['Location', 'location'],
                ['Website', 'website'],
                ['LinkedIn', 'linkedin'],
                ['GitHub', 'github'],
              ].map(([label, key]) => (
                <div key={key}>
                  <FieldLabel htmlFor={`builder-basics-${key}`}>{label}</FieldLabel>
                  <TextInput
                    id={`builder-basics-${key}`}
                    type="text"
                    value={structured.basics[key as keyof StructuredResume['basics']]}
                    onChange={event => mutateStructured(draft => {
                      draft.basics[key as keyof StructuredResume['basics']] = event.target.value
                    })}
                  />
                </div>
              ))}
            </div>
            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between gap-3">
                <FieldLabel htmlFor="builder-basics-summary">Summary</FieldLabel>
                <div className="flex flex-wrap gap-2">
                  <StarterChip
                    label="Insert startup profile"
                    onClick={() => mutateStructured(draft => {
                      draft.basics.summary = 'Engineer who ships product-facing systems quickly, improves reliability under load, and partners tightly with product to turn ambiguity into measurable execution.'
                    })}
                  />
                  <StarterChip
                    label="Insert leadership profile"
                    onClick={() => mutateStructured(draft => {
                      draft.basics.summary = 'Technical leader with a track record of scaling teams, clarifying platform strategy, and driving high-leverage systems work across product and infrastructure.'
                    })}
                  />
                </div>
              </div>
              <TextArea
                id="builder-basics-summary"
                value={structured.basics.summary}
                onFocus={() => setActiveSection('summary')}
                onChange={event => mutateStructured(draft => {
                  draft.basics.summary = event.target.value
                })}
                rows={5}
              />
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.experience = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Experience"
              sectionKey="experience"
              description="Describe your work and what you achieved. Use one achievement per line."
              order={structured.section_order}
              hidden={hidden.has('experience')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.experience.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['Role', 'title'],
                      ['Company', 'company'],
                      ['Location', 'location'],
                      ['Start Date', 'start_date'],
                      ['End Date', 'end_date'],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <FieldLabel htmlFor={`builder-experience-${entry.id}-${key}`}>{label}</FieldLabel>
                        <TextInput
                          id={`builder-experience-${entry.id}-${key}`}
                          type="text"
                          value={entry[key as keyof typeof entry] as string}
                          onFocus={() => setActiveSection('experience')}
                          onChange={event => mutateStructured(draft => {
                            draft.experience[idx][key as keyof typeof entry] = event.target.value as never
                          })}
                        />
                      </div>
                    ))}
                  </div>
                  <label className="mt-4 flex items-center gap-2 text-sm text-fg-2">
                    <input
                      type="checkbox"
                      checked={entry.current}
                      onChange={event => mutateStructured(draft => {
                        draft.experience[idx].current = event.target.checked
                        if (event.target.checked) draft.experience[idx].end_date = ''
                      })}
                    />
                    Current role
                  </label>
                  <div className="mt-4">
                    <FieldLabel htmlFor={`builder-experience-${entry.id}-summary`}>Role Summary</FieldLabel>
                    <TextArea
                      id={`builder-experience-${entry.id}-summary`}
                      rows={3}
                      value={entry.summary}
                      onFocus={() => setActiveSection('experience')}
                      onChange={event => mutateStructured(draft => {
                        draft.experience[idx].summary = event.target.value
                      })}
                    />
                  </div>
                  <div className="mt-4">
                    <FieldLabel htmlFor={`builder-experience-${entry.id}-bullets`}>Impact Bullets</FieldLabel>
                    <ListTextInput multiline separator="lines"
                      id={`builder-experience-${entry.id}-bullets`}
                      rows={5}
                      value={entry.bullets.join('\n')}
                      onFocus={() => setActiveSection('experience')}
                      onChange={value => mutateStructured(draft => {
                        const next = splitLinesWithIds(value, draft.experience[idx].bullets, draft.experience[idx].bullet_ids, draft.experience[idx].id)
                        draft.experience[idx].bullets = next.bullets
                        draft.experience[idx].bullet_ids = next.bullet_ids
                      })}
                    />
                  </div>
                  <div className="mt-4">
                    <FieldLabel htmlFor={`builder-experience-${entry.id}-technologies`}>Technologies</FieldLabel>
                    <ListTextInput separator="comma"
                      id={`builder-experience-${entry.id}-technologies`}
                      value={joinComma(entry.technologies)}
                      placeholder="Python, PostgreSQL, Kafka, AWS"
                      onFocus={() => setActiveSection('experience')}
                      onChange={value => mutateStructured(draft => {
                        draft.experience[idx].technologies = splitComma(value)
                      })}
                    />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.experience.splice(idx, 1)
                    })} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
                      Remove entry
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.experience.push({
                  id: createBuilderId('exp'),
                  title: '',
                  company: '',
                  location: '',
                  start_date: '',
                  end_date: '',
                  current: false,
                  summary: '',
                  bullets: [],
                  bullet_ids: [],
                  technologies: [],
                })
              })} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add experience
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.education = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Education"
              sectionKey="education"
              description="Keep it compact unless education is still a primary qualification signal."
              order={structured.section_order}
              hidden={hidden.has('education')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.education.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['Institution', 'institution'],
                      ['Degree', 'degree'],
                      ['Field', 'field'],
                      ['Location', 'location'],
                      ['Start Date', 'start_date'],
                      ['End Date', 'end_date'],
                      ['GPA', 'gpa'],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <FieldLabel htmlFor={`builder-education-${entry.id}-${key}`}>{label}</FieldLabel>
                        <TextInput
                          id={`builder-education-${entry.id}-${key}`}
                          type="text"
                          value={entry[key as keyof typeof entry] as string}
                          onFocus={() => setActiveSection('education')}
                          onChange={event => mutateStructured(draft => {
                            draft.education[idx][key as keyof typeof entry] = event.target.value as never
                          })}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="mt-4">
                    <FieldLabel htmlFor={`builder-education-${entry.id}-highlights`}>Highlights</FieldLabel>
                    <ListTextInput multiline separator="lines"
                      id={`builder-education-${entry.id}-highlights`}
                      rows={4}
                      value={entry.highlights.join('\n')}
                      placeholder="Honors, thesis, relevant coursework, leadership"
                      onFocus={() => setActiveSection('education')}
                      onChange={value => mutateStructured(draft => {
                        draft.education[idx].highlights = splitLines(value)
                      })}
                    />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.education.splice(idx, 1)
                    })} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
                      Remove education
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.education.push({
                  id: createBuilderId('edu'),
                  institution: '',
                  degree: '',
                  field: '',
                  location: '',
                  start_date: '',
                  end_date: '',
                  gpa: '',
                  highlights: [],
                })
              })} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add education
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.skills = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Skills"
              sectionKey="skills"
              description="Group related skills and separate each skill with a comma."
              order={structured.section_order}
              hidden={hidden.has('skills')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.skills.map((group, idx) => (
                <Card key={group.id}>
                  <FieldLabel htmlFor={`builder-skills-${group.id}-name`}>Group Name</FieldLabel>
                  <TextInput
                      id={`builder-skills-${group.id}-name`}
                    type="text"
                    value={group.name}
                    onFocus={() => setActiveSection('skills')}
                    onChange={event => mutateStructured(draft => {
                      draft.skills[idx].name = event.target.value
                    })}
                  />
                  <div className="mt-4">
                    <FieldLabel htmlFor={`builder-skills-${group.id}-keywords`}>Keywords</FieldLabel>
                    <ListTextInput multiline separator="comma"
                      id={`builder-skills-${group.id}-keywords`}
                      rows={3}
                      value={joinComma(group.keywords)}
                      onFocus={() => setActiveSection('skills')}
                      onChange={value => mutateStructured(draft => {
                        draft.skills[idx].keywords = splitComma(value)
                      })}
                    />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.skills.splice(idx, 1)
                    })} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
                      Remove skill group
                    </button>
                  </div>
                </Card>
              ))}
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => mutateStructured(draft => {
                  draft.skills.push({ id: createBuilderId('skill'), name: 'Core Skills', keywords: [] })
                })} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
                  <Plus className="mr-2 inline h-3.5 w-3.5" />
                  Add skill group
                </button>
                <StarterChip
                  label="Add engineering groups"
                  onClick={() => mutateStructured(draft => {
                    if (!draft.skills.length) {
                      draft.skills.push(
                        { id: createBuilderId('skill'), name: 'Languages', keywords: ['Python', 'TypeScript', 'SQL'] },
                        { id: createBuilderId('skill'), name: 'Platform', keywords: ['AWS', 'Docker', 'Kubernetes'] },
                      )
                    }
                  })}
                />
              </div>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.projects = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Projects"
              sectionKey="projects"
              description="Use projects to surface work that sharpens the candidate’s story, not to pad the page."
              order={structured.section_order}
              hidden={hidden.has('projects')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.projects.map((project, idx) => (
                <Card key={project.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['Project Name', 'name'],
                      ['Role', 'role'],
                      ['URL', 'url'],
                      ['Start Date', 'start_date'],
                      ['End Date', 'end_date'],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <FieldLabel htmlFor={`builder-projects-${project.id}-${key}`}>{label}</FieldLabel>
                        <TextInput
                          id={`builder-projects-${project.id}-${key}`}
                          type="text"
                          value={project[key as keyof typeof project] as string}
                          onFocus={() => setActiveSection('projects')}
                          onChange={event => mutateStructured(draft => {
                            draft.projects[idx][key as keyof typeof project] = event.target.value as never
                          })}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="mt-4">
                    <FieldLabel htmlFor={`builder-projects-${project.id}-description`}>Description</FieldLabel>
                    <TextArea
                      id={`builder-projects-${project.id}-description`}
                      rows={3}
                      value={project.description}
                      onFocus={() => setActiveSection('projects')}
                      onChange={event => mutateStructured(draft => {
                        draft.projects[idx].description = event.target.value
                      })}
                    />
                  </div>
                  <div className="mt-4">
                    <FieldLabel htmlFor={`builder-projects-${project.id}-bullets`}>Impact Bullets</FieldLabel>
                    <ListTextInput multiline separator="lines"
                      id={`builder-projects-${project.id}-bullets`}
                      rows={4}
                      value={project.bullets.join('\n')}
                      onFocus={() => setActiveSection('projects')}
                      onChange={value => mutateStructured(draft => {
                        const next = splitLinesWithIds(value, draft.projects[idx].bullets, draft.projects[idx].bullet_ids, draft.projects[idx].id)
                        draft.projects[idx].bullets = next.bullets
                        draft.projects[idx].bullet_ids = next.bullet_ids
                      })}
                    />
                  </div>
                  <div className="mt-4">
                    <FieldLabel htmlFor={`builder-projects-${project.id}-technologies`}>Technologies</FieldLabel>
                    <ListTextInput separator="comma"
                      id={`builder-projects-${project.id}-technologies`}
                      value={joinComma(project.technologies)}
                      onFocus={() => setActiveSection('projects')}
                      onChange={value => mutateStructured(draft => {
                        draft.projects[idx].technologies = splitComma(value)
                      })}
                    />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.projects.splice(idx, 1)
                    })} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
                      Remove project
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.projects.push({
                  id: createBuilderId('proj'),
                  name: '',
                  role: '',
                  url: '',
                  start_date: '',
                  end_date: '',
                  description: '',
                  bullets: [],
                  bullet_ids: [],
                  technologies: [],
                })
              })} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add project
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.certifications = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Certifications"
              sectionKey="certifications"
              description="Only keep credentials that materially support the target role or domain trust."
              order={structured.section_order}
              hidden={hidden.has('certifications')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.certifications.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['Name', 'name'],
                      ['Issuer', 'issuer'],
                      ['Date', 'date'],
                      ['URL', 'url'],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <FieldLabel htmlFor={`certification-${entry.id}-${key}`}>{label}</FieldLabel>
                        <TextInput
                          id={`certification-${entry.id}-${key}`}
                          type="text"
                          value={entry[key as keyof typeof entry] as string}
                          onFocus={() => setActiveSection('certifications')}
                          onChange={event => mutateStructured(draft => {
                            draft.certifications[idx][key as keyof typeof entry] = event.target.value as never
                          })}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.certifications.splice(idx, 1)
                    })} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
                      Remove certification
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.certifications.push({ id: createBuilderId('cert'), name: '', issuer: '', date: '', url: '' })
              })} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add certification
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.awards = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Awards"
              sectionKey="awards"
              description="Recognition should add proof, not noise."
              order={structured.section_order}
              hidden={hidden.has('awards')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.awards.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel htmlFor={`builder-awards-${entry.id}-name`}>Name</FieldLabel>
                      <TextInput
                      id={`builder-awards-${entry.id}-name`}
                        type="text"
                        value={entry.name}
                        onFocus={() => setActiveSection('awards')}
                        onChange={event => mutateStructured(draft => {
                          draft.awards[idx].name = event.target.value
                        })}
                      />
                    </div>
                    <div>
                      <FieldLabel htmlFor={`builder-awards-${entry.id}-detail`}>Detail</FieldLabel>
                      <TextInput
                      id={`builder-awards-${entry.id}-detail`}
                        type="text"
                        value={entry.detail}
                        onFocus={() => setActiveSection('awards')}
                        onChange={event => mutateStructured(draft => {
                          draft.awards[idx].detail = event.target.value
                        })}
                        />
                      </div>
                    </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.awards.splice(idx, 1)
                    })} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
                      Remove award
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.awards.push({ id: createBuilderId('award'), name: '', detail: '' })
              })} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add award
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.languages = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Languages"
              sectionKey="languages"
              description="State the language and actual proficiency rather than broad claims."
              order={structured.section_order}
              hidden={hidden.has('languages')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.languages.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel htmlFor={`builder-languages-${entry.id}-name`}>Language</FieldLabel>
                      <TextInput
                      id={`builder-languages-${entry.id}-name`}
                        type="text"
                        value={entry.name}
                        onFocus={() => setActiveSection('languages')}
                        onChange={event => mutateStructured(draft => {
                          draft.languages[idx].name = event.target.value
                        })}
                      />
                    </div>
                    <div>
                      <FieldLabel htmlFor={`builder-languages-${entry.id}-detail`}>Proficiency</FieldLabel>
                      <TextInput
                      id={`builder-languages-${entry.id}-detail`}
                        type="text"
                        value={entry.detail}
                        placeholder="Native, fluent, professional, conversational"
                        onFocus={() => setActiveSection('languages')}
                        onChange={event => mutateStructured(draft => {
                          draft.languages[idx].detail = event.target.value
                        })}
                        />
                      </div>
                    </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.languages.splice(idx, 1)
                    })} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
                      Remove language
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.languages.push({ id: createBuilderId('lang'), name: '', detail: '' })
              })} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add language
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.interests = node
            }}
            className="rounded-[var(--radius-lg)] border border-line bg-surface scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Interests"
              sectionKey="interests"
              description="Keep this optional and only use it when it sharpens memorability or fit."
              order={structured.section_order}
              hidden={hidden.has('interests')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.interests.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel htmlFor={`builder-interests-${entry.id}-name`}>Interest</FieldLabel>
                      <TextInput
                      id={`builder-interests-${entry.id}-name`}
                        type="text"
                        value={entry.name}
                        onFocus={() => setActiveSection('interests')}
                        onChange={event => mutateStructured(draft => {
                          draft.interests[idx].name = event.target.value
                        })}
                      />
                    </div>
                    <div>
                      <FieldLabel htmlFor={`builder-interests-${entry.id}-detail`}>Detail</FieldLabel>
                      <TextInput
                      id={`builder-interests-${entry.id}-detail`}
                        type="text"
                        value={entry.detail}
                        placeholder="Context, depth, leadership, or relevance"
                        onFocus={() => setActiveSection('interests')}
                        onChange={event => mutateStructured(draft => {
                          draft.interests[idx].detail = event.target.value
                        })}
                        />
                      </div>
                    </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.interests.splice(idx, 1)
                    })} className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
                      Remove interest
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.interests.push({ id: createBuilderId('interest'), name: '', detail: '' })
              })} className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add interest
              </button>
            </div>
          </section>
        </div>

        <div className="space-y-6">
          <BuilderPreview
            title={title}
            structured={structured}
            preview={livePreview}
            templateFamily={templateFamily}
            completenessScore={completenessScore}
            pageEstimate={pageEstimate}
            warnings={warnings}
          />

          <ElementVersionHistoryPanel
            resumeId={resumeId}
            elements={versionableElements}
            onRestore={restoreVersionableElement}
          />

          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
            <div className="flex items-center gap-2 text-sm font-semibold text-fg">
              <Sparkles className="h-4 w-4 text-accent-strong" />
              Builder Notes
            </div>
            <div className="mt-4 space-y-3 text-sm text-fg-2">
              <p>Section order and visibility update both the preview and the generated LaTeX.</p>
              <p>Changing the template keeps your content.</p>
              <p>Editing the code in the advanced editor pauses guided editing. You can return here and choose whether to replace those code changes.</p>
            </div>
            <div className="mt-5 rounded-[var(--radius-lg)] border border-line bg-surface p-4 text-xs text-fg-3">
              <FileText className="mr-2 inline h-3.5 w-3.5" />
              {builderStatus === 'detached' ? 'Guided editing paused' : 'Guided editing active'} · {selectedTemplate?.category_label || 'Résumé template'}
            </div>
          </section>
        </div>
      </section>
    </div>
  )
}
