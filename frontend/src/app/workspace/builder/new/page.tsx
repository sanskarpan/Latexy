'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, LayoutTemplate, Sparkles, Upload, Wand2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiClient,
  type BuilderMetricsResponse,
  type BuilderTemplateResponse,
} from '@/lib/api-client'
import {
  cloneStructuredResume,
  DEFAULT_STRUCTURED_RESUME,
  deriveBuilderMetrics,
} from '@/lib/resume-builder'

export default function NewBuilderPage() {
  const router = useRouter()
  const [title, setTitle] = useState('')
  const [templates, setTemplates] = useState<BuilderTemplateResponse[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('')
  const [structured, setStructured] = useState(cloneStructuredResume(DEFAULT_STRUCTURED_RESUME))
  const [seedMetrics, setSeedMetrics] = useState<BuilderMetricsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [uploading, setUploading] = useState(false)

  useEffect(() => {
    let cancelled = false
    apiClient.getBuilderTemplates()
      .then(result => {
        if (cancelled) return
        setTemplates(result)
        setSelectedTemplateId(result[0]?.id ?? '')
      })
      .catch(() => {
        if (!cancelled) toast.error('Failed to load builder templates')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const selectedTemplate = useMemo(
    () => templates.find(template => template.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates],
  )
  const effectiveMetrics = seedMetrics ?? deriveBuilderMetrics(structured)

  const handleSeedUpload = async (file: File | null) => {
    if (!file) return
    setUploading(true)
    try {
      const seeded = await apiClient.seedBuilderFromUpload(file)
      setStructured(cloneStructuredResume(seeded.structured_content))
      setSeedMetrics(seeded.metrics)
      if (!title.trim()) {
        setTitle(file.name.replace(/\.[^.]+$/, ''))
      }
      toast.success('Imported resume content into the builder')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to seed builder from upload')
    } finally {
      setUploading(false)
    }
  }

  const handleCreate = async () => {
    if (!title.trim()) {
      toast.error('Enter a resume title')
      return
    }
    if (!selectedTemplateId) {
      toast.error('Select a builder template')
      return
    }
    setCreating(true)
    try {
      const created = await apiClient.createBuilderResume({
        title: title.trim(),
        template_id: selectedTemplateId,
        structured_content: structured,
      })
      toast.success('Builder draft created')
      router.push(`/workspace/builder/${created.resume.id}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to create builder draft')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="content-shell space-y-8 pb-16">
      <header className="flex items-end justify-between gap-4 pt-2">
        <div>
          <p className="overline">Guided Builder</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Build from structured content</h1>
          <p className="mt-2 max-w-2xl text-sm text-zinc-400">
            This path is optimized for fast resume creation: pick a builder-native template, fill structured sections,
            and keep the advanced LaTeX editor as a fallback rather than the starting point.
          </p>
        </div>
        <Link href="/workspace/new" className="btn-ghost px-4 py-2 text-xs">
          Back to Create Resume
        </Link>
      </header>

      <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="surface-panel edge-highlight p-6">
          <label className="mb-2 block text-xs uppercase tracking-[0.14em] text-zinc-500">
            Resume Title
          </label>
          <input
            type="text"
            value={title}
            onChange={event => setTitle(event.target.value)}
            placeholder="Senior Backend Engineer — Core Resume"
            className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-base text-white outline-none transition focus:border-orange-300/50"
          />

          <div className="mt-6 flex items-center justify-between gap-4 rounded-2xl border border-white/10 bg-white/[0.02] p-4">
            <div>
              <p className="text-sm font-semibold text-white">Seed from an existing resume</p>
              <p className="mt-1 text-xs text-zinc-500">
                Upload PDF, DOCX, JSON Resume, or LinkedIn export to prefill the builder.
              </p>
            </div>
            <label className="btn-ghost cursor-pointer px-4 py-2 text-xs">
              <Upload className="mr-2 inline h-3.5 w-3.5" />
              {uploading ? 'Importing…' : 'Upload'}
              <input
                type="file"
                className="hidden"
                accept=".json,.pdf,.doc,.docx,.txt,.md,.html,.yaml,.yml,.toml,.xml,.tex"
                onChange={event => void handleSeedUpload(event.target.files?.[0] ?? null)}
              />
            </label>
          </div>
        </div>

        <div className="surface-panel edge-highlight p-6">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Sparkles className="h-4 w-4 text-orange-300" />
            Why use this builder
          </div>
          <div className="mt-4 grid gap-3 text-sm text-zinc-300">
            <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">Structured sections with live preview, autosave, and section reordering.</div>
            <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">Curated builder-native templates that stay stable under template swaps.</div>
            <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">Advanced LaTeX editor remains available after creation for power users.</div>
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
          <div key={item.title} className="surface-panel edge-highlight p-6">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <CheckCircle2 className="h-4 w-4 text-orange-300" />
              {item.title}
            </div>
            <p className="mt-3 text-sm text-zinc-400">{item.description}</p>
          </div>
        ))}
      </section>

      <section className="surface-panel edge-highlight p-6">
        <div className="mb-5 flex items-center gap-2">
          <LayoutTemplate className="h-4 w-4 text-orange-300" />
          <h2 className="text-sm font-semibold text-white">Choose a builder-native template</h2>
        </div>
        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, idx) => (
              <div key={idx} className="h-48 animate-pulse rounded-2xl bg-white/5" />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {templates.map(template => (
              <button
                key={template.id}
                type="button"
                onClick={() => setSelectedTemplateId(template.id)}
                className={`rounded-2xl border p-5 text-left transition ${
                  template.id === selectedTemplateId
                    ? 'border-orange-300/40 bg-orange-300/[0.06]'
                    : 'border-white/10 bg-black/20 hover:bg-white/[0.03]'
                }`}
              >
                <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">{template.category_label}</p>
                <h3 className="mt-2 text-lg font-semibold text-white">{template.name}</h3>
                <p className="mt-2 text-sm text-zinc-400">
                  {template.description || `${template.template_family} builder layout`}
                </p>
                <p className="mt-4 text-xs text-zinc-500">Family: {template.template_family}</p>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="surface-panel edge-highlight p-6">
          <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Seed Preview</p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-2xl border border-white/8 bg-black/20 p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Basics</p>
              <p className="mt-2 text-sm text-white">{structured.basics.name || 'No name imported yet'}</p>
              <p className="mt-1 text-xs text-zinc-400">{structured.basics.label || 'Add role headline later'}</p>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/20 p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Sections</p>
              <p className="mt-2 text-sm text-white">
                {[
                  structured.experience.length ? `${structured.experience.length} experience` : null,
                  structured.education.length ? `${structured.education.length} education` : null,
                  structured.skills.length ? `${structured.skills.length} skill groups` : null,
                  structured.projects.length ? `${structured.projects.length} projects` : null,
                ].filter(Boolean).join(' · ') || 'No imported sections yet'}
              </p>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/20 p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Readiness</p>
              <p className="mt-2 text-sm text-white">{effectiveMetrics.completeness_score}% complete</p>
              <p className="mt-1 text-xs text-zinc-400">
                {effectiveMetrics.missing_sections.length
                  ? `Missing: ${effectiveMetrics.missing_sections.join(', ')}`
                  : 'Core sections are present'}
              </p>
            </div>
          </div>
          {effectiveMetrics.warnings.length ? (
            <div className="mt-4 space-y-2">
              {effectiveMetrics.warnings.map(warning => (
                <div key={warning} className="rounded-xl border border-amber-300/20 bg-amber-300/[0.05] px-3 py-2 text-xs text-amber-50/90">
                  {warning}
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="surface-panel edge-highlight p-6">
          <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Ready</p>
          <h2 className="mt-2 text-xl font-semibold text-white">
            {selectedTemplate?.name || 'Select a template first'}
          </h2>
          <p className="mt-2 text-sm text-zinc-400">
            The builder will create a structured draft first, then keep LaTeX in sync behind the scenes.
          </p>
          <div className="mt-5 rounded-2xl border border-white/8 bg-black/20 p-4 text-sm text-zinc-300">
            <div className="flex items-center gap-2 font-semibold text-white">
              <Wand2 className="h-4 w-4 text-orange-300" />
              Builder first, editor second
            </div>
            <p className="mt-2 text-zinc-400">
              This path is best when you want guided UX, richer section controls, safer template switching, and fewer chances
              to break layout details manually.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={creating || loading || !selectedTemplateId}
            className="btn-accent mt-6 w-full px-4 py-3 text-sm disabled:opacity-50"
          >
            {creating ? 'Creating builder draft…' : 'Start Guided Builder'}
          </button>
        </div>
      </section>
    </div>
  )
}
