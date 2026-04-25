'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Search, Upload, LayoutTemplate, X, Linkedin, PackageOpen } from 'lucide-react'
import { toast } from 'sonner'

import { apiClient } from '@/lib/api-client'
import type { TemplateResponse, TemplateCategoryCount } from '@/lib/api-client'
import MultiFormatUpload from '@/components/MultiFormatUpload'
import ImportFromBuilderWizard from '@/components/ImportFromBuilderWizard'
import TemplateCard from '@/components/TemplateCard'
import TemplatePreviewModal from '@/components/TemplatePreviewModal'

// ------------------------------------------------------------------ //
//  Blank resume content (always available as a starter)              //
// ------------------------------------------------------------------ //

const BLANK_CONTENT = `\\documentclass[11pt,a4paper]{article}
\\usepackage[top=0.6in,bottom=0.6in,left=0.7in,right=0.7in]{geometry}
\\usepackage[T1]{fontenc}
\\usepackage[utf8]{inputenc}
\\usepackage{enumitem}
\\usepackage{hyperref}
\\setlist{nosep,leftmargin=*}
\\pagestyle{empty}

\\begin{document}

\\begin{center}
  {\\LARGE\\textbf{Your Name}} \\\\[2pt]
  your@email.com $\\mid$ linkedin.com/in/yourprofile $\\mid$ github.com/username
\\end{center}

\\section*{Summary}
Briefly describe your background, key strengths, and career goals here.

\\section*{Experience}
\\textbf{Company Name} \\hfill Jan 2023 -- Present \\\\
\\textit{Job Title}
\\begin{itemize}
  \\item Key achievement or responsibility with measurable impact
  \\item Another important contribution to the team or organisation
\\end{itemize}

\\section*{Education}
\\textbf{University Name} \\hfill 2018 -- 2022 \\\\
B.S. in Your Major

\\section*{Skills}
Python, TypeScript, SQL, Docker, AWS, Git

\\end{document}`

// ------------------------------------------------------------------ //
//  Category tab order                                                 //
// ------------------------------------------------------------------ //

const CATEGORY_ORDER = [
  'software_engineering', 'finance', 'academic', 'creative',
  'minimal', 'ats_safe', 'two_column', 'executive',
  'marketing', 'medical', 'legal', 'graduate',
]

// ------------------------------------------------------------------ //
//  Page component                                                     //
// ------------------------------------------------------------------ //

type Mode = 'template' | 'import' | 'linkedin' | 'builder'

export default function NewResumePage() {
  const router = useRouter()

  // ---- form state ----
  const [title, setTitle] = useState('')
  const [mode, setMode] = useState<Mode>('template')
  const [importedContent, setImportedContent] = useState('')

  // ---- template gallery state ----
  const [templates, setTemplates] = useState<TemplateResponse[]>([])
  const [categories, setCategories] = useState<TemplateCategoryCount[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [loadingTemplates, setLoadingTemplates] = useState(true)

  // ---- preview modal ----
  const [previewTemplateId, setPreviewTemplateId] = useState<string | null>(null)

  // ---- submit state ----
  const [isCreating, setIsCreating] = useState(false)

  // ---- fetch templates on mount ----
  useEffect(() => {
    let cancelled = false
    setLoadingTemplates(true)
    Promise.all([apiClient.getTemplates(), apiClient.getTemplateCategories()])
      .then(([tmpl, cats]) => {
        if (cancelled) return
        setTemplates(tmpl)
        setCategories(cats)
      })
      .catch(() => {
        if (!cancelled) toast.error('Failed to load templates')
      })
      .finally(() => {
        if (!cancelled) setLoadingTemplates(false)
      })
    return () => { cancelled = true }
  }, [])

  // ---- filtered templates (client-side) ----
  const filteredTemplates = useMemo(() => {
    let list = templates
    if (activeCategory !== 'all') {
      list = list.filter(t => t.category === activeCategory)
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter(t =>
        t.name.toLowerCase().includes(q) ||
        (t.description ?? '').toLowerCase().includes(q) ||
        t.tags.some(tag => tag.toLowerCase().includes(q))
      )
    }
    return list
  }, [templates, activeCategory, search])

  // ---- sorted category tabs ----
  const sortedCategories = useMemo(() =>
    [...categories].sort((a, b) => {
      const ia = CATEGORY_ORDER.indexOf(a.category)
      const ib = CATEGORY_ORDER.indexOf(b.category)
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    }),
  [categories])

  // ---- handlers ----
  const handleUseTemplate = useCallback(async (id: string) => {
    const trimmedTitle = title.trim()
    const template = templates.find(t => t.id === id)
    const finalTitle = trimmedTitle || template?.name || 'Untitled Resume'

    setIsCreating(true)
    try {
      const result = await apiClient.useTemplate(id, finalTitle)
      toast.success('Resume created from template')
      router.push(`/workspace/${result.resume_id}/edit`)
    } catch {
      toast.error('Failed to create resume')
      setIsCreating(false)
    }
  }, [title, templates, router])

  const handleSelectTemplate = useCallback((id: string) => {
    handleUseTemplate(id)
  }, [handleUseTemplate])

  const handlePreviewTemplate = useCallback((id: string) => {
    setPreviewTemplateId(id)
  }, [])

  const handleUseFromPreview = useCallback((id: string) => {
    setPreviewTemplateId(null)
    handleUseTemplate(id)
  }, [handleUseTemplate])

  const handleCreate = async () => {
    const trimmedTitle = title.trim()
    if (!trimmedTitle) {
      toast.error('Please enter a resume title')
      return
    }

    if ((mode === 'import' || mode === 'linkedin' || mode === 'builder') && !importedContent) {
      toast.error('Please upload a file first')
      return
    }

    setIsCreating(true)
    try {
      if (mode === 'import' || mode === 'linkedin' || mode === 'builder') {
        const created = await apiClient.createResume({
          title: trimmedTitle,
          latex_content: importedContent,
          is_template: false,
        })
        toast.success('Resume created from import')
        router.push(`/workspace/${created.id}/edit`)
      } else {
        // Blank resume
        const created = await apiClient.createResume({
          title: trimmedTitle,
          latex_content: BLANK_CONTENT,
          is_template: false,
        })
        toast.success('Blank resume created')
        router.push(`/workspace/${created.id}/edit`)
      }
    } catch {
      toast.error('Failed to create resume')
      setIsCreating(false)
    }
  }

  const canCreate =
    !!title.trim() &&
    !isCreating &&
    ((mode === 'import' || mode === 'linkedin' || mode === 'builder') ? !!importedContent : true)

  // ---------------------------------------------------------------- //
  //  Render                                                           //
  // ---------------------------------------------------------------- //

  return (
    <>
      <div className="content-shell space-y-7 pb-16">
        {/* Header */}
        <header className="flex items-end justify-between gap-4">
          <div>
            <p className="overline">Workspace</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Create Resume</h1>
            <p className="mt-1 text-sm text-zinc-400">Choose a template or import an existing file.</p>
          </div>
          <Link href="/workspace" className="btn-ghost px-4 py-2 text-xs">
            Back to Workspace
          </Link>
        </header>

        {/* Title input */}
        <section className="surface-panel edge-highlight p-6">
          <label className="mb-2 block text-xs uppercase tracking-[0.14em] text-zinc-500">
            Resume Title
          </label>
          <input
            type="text"
            placeholder="Senior Backend Engineer – Q3 2026"
            value={title}
            onChange={e => setTitle(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && canCreate) handleCreate() }}
            className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-base text-white outline-none transition focus:border-orange-300/50"
          />
        </section>

        {/* Mode toggle */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <button
            onClick={() => { setMode('template'); setImportedContent('') }}
            className={`surface-panel edge-highlight flex items-start gap-3 p-5 text-left transition ${
              mode === 'template'
                ? 'border-orange-300/35 bg-orange-300/[0.05]'
                : 'hover:bg-white/[0.03]'
            }`}
          >
            <LayoutTemplate className="mt-0.5 h-5 w-5 shrink-0 text-orange-300/70" />
            <div>
              <h2 className="text-sm font-semibold text-white">Use Template</h2>
              <p className="mt-0.5 text-xs text-zinc-400">Pick from 50+ LaTeX templates, ready to edit.</p>
            </div>
          </button>

          <button
            onClick={() => { setMode('import'); setImportedContent('') }}
            className={`surface-panel edge-highlight flex items-start gap-3 p-5 text-left transition ${
              mode === 'import'
                ? 'border-orange-300/35 bg-orange-300/[0.05]'
                : 'hover:bg-white/[0.03]'
            }`}
          >
            <Upload className="mt-0.5 h-5 w-5 shrink-0 text-orange-300/70" />
            <div>
              <h2 className="text-sm font-semibold text-white">Import File</h2>
              <p className="mt-0.5 text-xs text-zinc-400">Upload PDF, Word, Markdown, LaTeX, or more.</p>
            </div>
          </button>

          <button
            onClick={() => { setMode('linkedin'); setImportedContent('') }}
            className={`surface-panel edge-highlight flex items-start gap-3 p-5 text-left transition ${
              mode === 'linkedin'
                ? 'border-sky-400/35 bg-sky-400/[0.05]'
                : 'hover:bg-white/[0.03]'
            }`}
          >
            <Linkedin className="mt-0.5 h-5 w-5 shrink-0 text-sky-400/80" />
            <div>
              <h2 className="text-sm font-semibold text-white">Import from LinkedIn</h2>
              <p className="mt-0.5 text-xs text-zinc-400">Export your LinkedIn profile as PDF and import it.</p>
            </div>
          </button>

          <button
            onClick={() => { setMode('builder'); setImportedContent('') }}
            className={`surface-panel edge-highlight flex items-start gap-3 p-5 text-left transition ${
              mode === 'builder'
                ? 'border-violet-400/35 bg-violet-400/[0.05]'
                : 'hover:bg-white/[0.03]'
            }`}
          >
            <PackageOpen className="mt-0.5 h-5 w-5 shrink-0 text-violet-400/80" />
            <div>
              <h2 className="text-sm font-semibold text-white">Import from Builder</h2>
              <p className="mt-0.5 text-xs text-zinc-400">Kickresume, Resume.io, Novoresume, and more.</p>
            </div>
          </button>
        </div>

        {/* --- IMPORT MODE --- */}
        {mode === 'import' && (
          <section className="surface-panel edge-highlight p-6">
            <MultiFormatUpload onFileUpload={setImportedContent} />
            {importedContent && (
              <p className="mt-3 text-xs uppercase tracking-[0.12em] text-emerald-300">
                File parsed — {importedContent.length.toLocaleString()} characters ready
              </p>
            )}
          </section>
        )}

        {/* --- LINKEDIN MODE --- */}
        {mode === 'linkedin' && (
          <section className="surface-panel edge-highlight p-6 space-y-5">
            {/* Step-by-step instructions */}
            <div className="rounded-xl border border-sky-400/15 bg-sky-400/[0.04] p-4">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-sky-300/80">
                <Linkedin className="h-3.5 w-3.5" />
                How to export your LinkedIn profile
              </h3>
              <ol className="mt-3 space-y-1.5 text-xs text-zinc-400">
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-sky-400/15 text-[10px] font-bold text-sky-300">1</span>
                  Go to <span className="text-sky-300">linkedin.com</span> and open your profile
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-sky-400/15 text-[10px] font-bold text-sky-300">2</span>
                  Click <span className="font-medium text-zinc-300">&ldquo;More&rdquo; (•••)</span> under your profile photo
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-sky-400/15 text-[10px] font-bold text-sky-300">3</span>
                  Click <span className="font-medium text-zinc-300">&ldquo;Save to PDF&rdquo;</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-sky-400/15 text-[10px] font-bold text-sky-300">4</span>
                  Upload the downloaded PDF below
                </li>
              </ol>
            </div>

            {/* Upload area — PDF only, LinkedIn-optimised prompt */}
            <MultiFormatUpload onFileUpload={setImportedContent} sourceHint="linkedin" />
            {importedContent && (
              <p className="text-xs uppercase tracking-[0.12em] text-emerald-300">
                Profile parsed — {importedContent.length.toLocaleString()} characters ready
              </p>
            )}
          </section>
        )}

        {/* --- BUILDER MODE --- */}
        {mode === 'builder' && (
          <section className="surface-panel edge-highlight p-6">
            {importedContent ? (
              <p className="text-xs uppercase tracking-[0.12em] text-emerald-300">
                Resume imported — {importedContent.length.toLocaleString()} characters ready
              </p>
            ) : (
              <ImportFromBuilderWizard onComplete={setImportedContent} />
            )}
          </section>
        )}

        {/* --- TEMPLATE MODE --- */}
        {mode === 'template' && (
          <section className="space-y-5">
            {/* Blank resume option + search bar */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              {/* Search */}
              <div className="relative w-full sm:max-w-xs">
                <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
                <input
                  type="text"
                  placeholder="Search templates…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-black/40 py-2 pl-9 pr-9 text-sm text-white outline-none transition placeholder:text-zinc-600 focus:border-orange-300/40"
                />
                {search && (
                  <button
                    onClick={() => setSearch('')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              {/* Blank option */}
              <button
                onClick={handleCreate}
                disabled={isCreating}
                className="shrink-0 rounded-xl border border-white/10 px-4 py-2 text-xs font-medium text-zinc-500 transition hover:border-white/20 hover:text-zinc-300 disabled:opacity-40"
              >
                Start from Blank
              </button>
            </div>

            {/* Category tabs */}
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setActiveCategory('all')}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                  activeCategory === 'all'
                    ? 'border-orange-300/40 bg-orange-300/10 text-orange-200'
                    : 'border-white/10 text-zinc-500 hover:border-white/20 hover:text-zinc-300'
                }`}
              >
                All ({templates.length})
              </button>
              {sortedCategories.map(cat => (
                <button
                  key={cat.category}
                  onClick={() => setActiveCategory(cat.category)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                    activeCategory === cat.category
                      ? 'border-orange-300/40 bg-orange-300/10 text-orange-200'
                      : 'border-white/10 text-zinc-500 hover:border-white/20 hover:text-zinc-300'
                  }`}
                >
                  {cat.label} ({cat.count})
                </button>
              ))}
            </div>

            {/* Template grid */}
            {loadingTemplates ? (
              /* Skeleton */
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="h-64 animate-pulse rounded-xl bg-white/5" />
                ))}
              </div>
            ) : filteredTemplates.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-16 text-center">
                <p className="text-sm text-zinc-500">No templates found</p>
                {search && (
                  <button onClick={() => setSearch('')} className="text-xs text-orange-300 hover:underline">
                    Clear search
                  </button>
                )}
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {filteredTemplates.map(template => (
                  <TemplateCard
                    key={template.id}
                    template={template}
                    onSelect={handleSelectTemplate}
                    onPreview={handlePreviewTemplate}
                    disabled={isCreating}
                  />
                ))}
              </div>
            )}
          </section>
        )}

        {/* Create button — shown for import/linkedin mode */}
        {(mode === 'import' || mode === 'linkedin') && (
          <div className="flex items-center justify-end gap-3">
            <button
              onClick={handleCreate}
              disabled={!canCreate}
              className="btn-accent px-8 py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isCreating ? 'Creating…' : 'Create Resume'}
            </button>
          </div>
        )}
      </div>

      {/* Preview modal (portal-like; renders on top) */}
      <TemplatePreviewModal
        templateId={previewTemplateId}
        onUse={handleUseFromPreview}
        onClose={() => setPreviewTemplateId(null)}
      />
    </>
  )
}
