'use client'

import { useCapabilityDraftRecovery } from '@/contexts/CapabilityRecoveryContext'
import { useEntitlements } from '@/contexts/EntitlementsContext'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, LayoutTemplate, Sparkles, Upload, Wand2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiClient,
  BuilderSeedValidationError,
  type BuilderMetricsResponse,
  type BuilderTemplateResponse,
  type ResumeValidationIssue,
} from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import {
  cloneStructuredResume,
  DEFAULT_STRUCTURED_RESUME,
  deriveBuilderMetrics,
} from '@/lib/resume-builder'

type BuilderSession = NonNullable<ReturnType<typeof useRequireAuth>['session']>

export default function NewBuilderPage() {
  const { session, isPending: sessionLoading, error: sessionError } = useRequireAuth()

  if (sessionLoading && !session) {
    return <div className="content-shell py-16 text-sm text-fg-2">Loading builder…</div>
  }
  if (sessionError && !session) {
    return (
      <div className="content-shell py-16">
        <div role="alert" className="mx-auto max-w-lg rounded-[var(--radius-lg)] border border-err/20 bg-err/10 p-6 text-center">
          <h1 className="text-lg font-semibold text-fg">Builder could not be loaded</h1>
          <p className="mt-2 text-sm text-fg-2">Your session could not be verified. Check your connection and retry.</p>
          <button type="button" onClick={() => window.location.reload()} className="mt-5 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-medium text-accent-fg">
            Retry
          </button>
        </div>
      </div>
    )
  }
  if (!session) return null

  // The form owns all mutable draft state. Remounting it on an authenticated
  // identity change prevents an in-flight create/upload from crossing owners,
  // including an A → B → A account switch.
  return <NewBuilderForm key={session.user.id} session={session} authUnverified={Boolean(sessionLoading || sessionError)} />
}

function NewBuilderForm({ session, authUnverified }: { session: BuilderSession; authUnverified: boolean }) {
  const { can } = useEntitlements()
  const router = useRouter()
  const mountedRef = useRef(true)
  const authVerifiedRef = useRef(!authUnverified)
  authVerifiedRef.current = !authUnverified && can('b08')
  const [title, setTitle] = useState('')
  const [templates, setTemplates] = useState<BuilderTemplateResponse[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('')
  const [structured, setStructured] = useState(cloneStructuredResume(DEFAULT_STRUCTURED_RESUME))
  useCapabilityDraftRecovery(session.user.id, 'latexy-new-builder-draft.json', Boolean(title.trim()) || JSON.stringify(structured) !== JSON.stringify(DEFAULT_STRUCTURED_RESUME), {
    format: 'latexy-builder-draft', version: 1, title, template_id: selectedTemplateId, structured_content: structured,
  })
  const [seedMetrics, setSeedMetrics] = useState<BuilderMetricsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [creating, setCreating] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadIssues, setUploadIssues] = useState<ResumeValidationIssue[]>([])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    apiClient.getBuilderTemplates()
      .then(result => {
        if (cancelled) return
        setTemplates(result)
        setSelectedTemplateId(result[0]?.id ?? '')
      })
      .catch((error) => {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : 'Failed to load builder templates')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [loadAttempt])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const isCurrentRequest = () => mountedRef.current && authVerifiedRef.current

  const selectedTemplate = useMemo(
    () => templates.find(template => template.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates],
  )
  const effectiveMetrics = seedMetrics ?? deriveBuilderMetrics(structured)

  const handleSeedUpload = async (file: File | null) => {
    if (!file) return
    if (!isCurrentRequest()) {
      toast.error('Session verification is still in progress. Please try again.')
      return
    }
    setUploading(true)
    setUploadIssues([])
    try {
      const seeded = await apiClient.seedBuilderFromUpload(file)
      if (!isCurrentRequest()) return
      setStructured(cloneStructuredResume(seeded.structured_content))
      setSeedMetrics(seeded.metrics)
      if (!title.trim()) {
        setTitle(file.name.replace(/\.[^.]+$/, ''))
      }
      toast.success('Imported resume content into the builder')
      for (const warning of seeded.interchange_warnings ?? []) toast.warning(warning)
    } catch (error) {
      if (!isCurrentRequest()) return
      if (error instanceof BuilderSeedValidationError) {
        setUploadIssues(error.issues)
      }
      toast.error(error instanceof Error ? error.message : 'Failed to seed builder from upload')
    } finally {
      if (mountedRef.current) setUploading(false)
    }
  }

  const handleCreate = async () => {
    if (!isCurrentRequest()) {
      toast.error('Session verification is still in progress. Please try again.')
      return
    }
    if (!title.trim()) {
      toast.error('Enter a resume title')
      return
    }
    if (!selectedTemplateId) {
      toast.error('Select a builder template')
      return
    }
    if (title.trim().length > 255) {
      toast.error('Resume titles must be 255 characters or fewer')
      return
    }
    setCreating(true)
    try {
      const created = await apiClient.createBuilderResume({
        title: title.trim(),
        template_id: selectedTemplateId,
        structured_content: structured,
      })
      if (!isCurrentRequest()) return
      toast.success('Builder draft created')
      router.push(`/workspace/builder/${created.resume.id}`)
    } catch (error) {
      if (!isCurrentRequest()) return
      toast.error(error instanceof Error ? error.message : 'Failed to create builder draft')
    } finally {
      if (mountedRef.current) setCreating(false)
    }
  }

  if (loading) {
    return <div className="content-shell py-16 text-sm text-fg-2">Loading builder templates…</div>
  }

  if (loadError) {
    return (
      <div className="content-shell py-16">
        <div role="alert" className="mx-auto max-w-lg rounded-[var(--radius-lg)] border border-err/20 bg-err/10 p-6 text-center">
          <h1 className="text-lg font-semibold text-fg">Builder could not be loaded</h1>
          <p className="mt-2 text-sm text-fg-2">{loadError}</p>
          <div className="mt-5 flex justify-center gap-2">
            <Link href="/workspace/new" className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-sm text-fg-2">Back</Link>
            <button type="button" onClick={() => setLoadAttempt(value => value + 1)} className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-medium text-accent-fg">Retry</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="content-shell space-y-8 pb-16">
      <header className="flex items-end justify-between gap-4 pt-2">
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Guided Builder</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">Build from structured content</h1>
          <p className="mt-2 max-w-2xl text-sm text-fg-2">
            This path is optimized for fast resume creation: pick a builder-native template, fill structured sections,
            and keep the advanced LaTeX editor as a fallback rather than the starting point.
          </p>
        </div>
        <Link href="/workspace/new" className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2">
          Back to Create Resume
        </Link>
      </header>

      <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
          <label className="mb-2 block text-xs uppercase tracking-[0.14em] text-fg-3">
            Resume Title
          </label>
          <input
            type="text"
            value={title}
            onChange={event => setTitle(event.target.value)}
            maxLength={255}
            placeholder="Senior Backend Engineer — Core Resume"
            className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-4 py-3 text-base text-fg outline-none transition focus:border-accent"
          />

          <div className="mt-6 flex items-center justify-between gap-4 rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">
            <div>
              <p className="text-sm font-semibold text-fg">Seed from an existing resume</p>
              <p className="mt-1 text-xs text-fg-3">
                Upload PDF, DOCX, JSON Resume, or LinkedIn export to prefill the builder.
              </p>
            </div>
            <label className="cursor-pointer rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2">
              <Upload className="mr-2 inline h-3.5 w-3.5" />
              {uploading ? 'Importing…' : 'Upload'}
              <input
                type="file"
                className="hidden"
                disabled={uploading}
                accept=".json,.pdf,.doc,.docx,.txt,.md,.html,.yaml,.yml,.toml,.xml,.tex"
                onChange={event => void handleSeedUpload(event.target.files?.[0] ?? null)}
              />
            </label>
          </div>
          {uploadIssues.length > 0 && (
            <div role="alert" className="mt-3 rounded-[var(--radius-md)] border border-err/30 bg-err/5 p-4">
              <p className="text-sm font-semibold text-err">Import validation failed</p>
              <ul className="mt-2 space-y-2 text-xs text-fg-2">
                {uploadIssues.map((issue, index) => (
                  <li key={`${issue.path}-${issue.line ?? 'unknown'}-${index}`}>
                    <code className="font-mono text-err">{issue.path}</code>
                    {issue.line != null && (
                      <span> — line {issue.line}{issue.column != null ? `, column ${issue.column}` : ''}</span>
                    )}
                    <span>: {issue.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
          <div className="flex items-center gap-2 text-sm font-semibold text-fg">
            <Sparkles className="h-4 w-4 text-accent-strong" />
            Why use this builder
          </div>
          <div className="mt-4 grid gap-3 text-sm text-fg-2">
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">Structured sections with live preview, autosave, and section reordering.</div>
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">Curated builder-native templates that stay stable under template swaps.</div>
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">Advanced LaTeX editor remains available after creation for power users.</div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        {[
          {
            title: '1. Seed',
            description: 'Start from a past resume, LinkedIn export, or JSON Resume so you do not rebuild the basics manually.',
          },
          {
            title: '2. Shape',
            description: 'Tune the headline, impact bullets, skills, and sections with a live structured editing surface.',
          },
          {
            title: '3. Ship',
            description: 'Swap builder-safe templates, keep page density in check, and open the advanced editor only when needed.',
          },
        ].map(item => (
          <div key={item.title} className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
            <div className="flex items-center gap-2 text-sm font-semibold text-fg">
              <CheckCircle2 className="h-4 w-4 text-accent-strong" />
              {item.title}
            </div>
            <p className="mt-3 text-sm text-fg-2">{item.description}</p>
          </div>
        ))}
      </section>

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
        <div className="mb-5 flex items-center gap-2">
          <LayoutTemplate className="h-4 w-4 text-accent-strong" />
          <h2 className="text-sm font-semibold text-fg">Choose a builder-native template</h2>
        </div>
        {templates.length === 0 ? (
          <div role="status" className="rounded-[var(--radius-lg)] border border-line bg-surface-2 p-6 text-sm text-fg-2">
            No builder-compatible templates are currently available.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {templates.map(template => (
              <button
                key={template.id}
                type="button"
                onClick={() => setSelectedTemplateId(template.id)}
                className={`rounded-[var(--radius-lg)] border p-5 text-left transition ${
                  template.id === selectedTemplateId
                    ? 'border-accent bg-accent-soft'
                    : 'border-line bg-surface-2 hover:bg-surface-2'
                }`}
              >
                <p className="text-xs uppercase tracking-[0.16em] text-fg-3">{template.category_label}</p>
                <h3 className="mt-2 text-lg font-semibold text-fg">{template.name}</h3>
                <p className="mt-2 text-sm text-fg-2">
                  {template.description || `${template.template_family} builder layout`}
                </p>
                <p className="mt-4 text-xs text-fg-3">Family: {template.template_family}</p>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
          <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Seed Preview</p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Basics</p>
              <p className="mt-2 text-sm text-fg">{structured.basics.name || 'No name imported yet'}</p>
              <p className="mt-1 text-xs text-fg-2">{structured.basics.label || 'Add role headline later'}</p>
            </div>
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Sections</p>
              <p className="mt-2 text-sm text-fg">
                {[
                  structured.experience.length ? `${structured.experience.length} experience` : null,
                  structured.education.length ? `${structured.education.length} education` : null,
                  structured.skills.length ? `${structured.skills.length} skill groups` : null,
                  structured.projects.length ? `${structured.projects.length} projects` : null,
                ].filter(Boolean).join(' · ') || 'No imported sections yet'}
              </p>
            </div>
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Readiness</p>
              <p className="mt-2 text-sm text-fg">{effectiveMetrics.completeness_score}% complete</p>
              <p className="mt-1 text-xs text-fg-2">
                {effectiveMetrics.missing_sections.length
                  ? `Missing: ${effectiveMetrics.missing_sections.join(', ')}`
                  : 'Core sections are present'}
              </p>
            </div>
          </div>
          {effectiveMetrics.warnings.length ? (
            <div className="mt-4 space-y-2">
              {effectiveMetrics.warnings.map(warning => (
                <div key={warning} className="rounded-[var(--radius-md)] border border-warn/20 bg-warn/[0.05] px-3 py-2 text-xs text-warn">
                  {warning}
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
          <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Ready</p>
          <h2 className="mt-2 text-xl font-semibold text-fg">
            {selectedTemplate?.name || 'Select a template first'}
          </h2>
          <p className="mt-2 text-sm text-fg-2">
            The builder will create a structured draft first, then keep LaTeX in sync behind the scenes.
          </p>
          <div className="mt-5 rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4 text-sm text-fg-2">
            <div className="flex items-center gap-2 font-semibold text-fg">
              <Wand2 className="h-4 w-4 text-accent-strong" />
              Builder first, editor second
            </div>
            <p className="mt-2 text-fg-2">
              This path is best when you want guided UX, richer section controls, safer template switching, and fewer chances
              to break layout details manually.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={creating || loading || !selectedTemplateId}
            className="mt-6 w-full rounded-[var(--radius-md)] bg-accent px-4 py-3 text-sm font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50"
          >
            {creating ? 'Creating builder draft…' : 'Start Guided Builder'}
          </button>
        </div>
      </section>
    </div>
  )
}
