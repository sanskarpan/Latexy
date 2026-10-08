'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ExternalLink, Search, Upload, LayoutTemplate, X, PackageOpen, Sparkles, Loader2 } from 'lucide-react'
import { Linkedin } from '@/components/icons/brand-icons'
import { toast } from 'sonner'
import { useRequireAuth } from '@/hooks/useRequireAuth'

import { apiClient } from '@/lib/api-client'
import type { TemplateResponse, TemplateCategoryCount } from '@/lib/api-client'
import MultiFormatUpload from '@/components/MultiFormatUpload'
import ImportFromBuilderWizard from '@/components/ImportFromBuilderWizard'
import PdfImportWizard from '@/components/PdfImportWizard'
import TemplateCard from '@/components/TemplateCard'
import TemplatePreviewModal from '@/components/TemplatePreviewModal'
import LoadingSpinner from '@/components/LoadingSpinner'
import SessionLoadError from '@/components/SessionLoadError'
import {
  formatLinkedInArchiveRequestDate,
  LINKEDIN_DATA_EXPORT_URL,
  readLinkedInArchiveRequest,
  rememberLinkedInArchiveRequest,
} from '@/lib/linkedin-import-progress'
import { TEMPLATE_CATEGORY_ORDER } from '@/lib/template-categories'

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
//  Page component                                                     //
// ------------------------------------------------------------------ //

type Mode = 'template' | 'import' | 'linkedin' | 'builder'
type TemplatePreviewIdentity = { templateId: string | null; generation: number }
type TemplateUseRequest = {
  token: number
  ownerId: string | null
  ownerGeneration: number
  preview?: { templateId: string; generation: number }
}
type CreateRequest = {
  token: number
  ownerId: string
  ownerGeneration: number
}
type NewResumeOwnerIdentity = { ownerId: string | null; generation: number }
type NewResumeOwnerIdentityRef = { current: NewResumeOwnerIdentity }
type NewResumeSession = NonNullable<ReturnType<typeof useRequireAuth>['session']>

export default function NewResumePage() {
  const { session, isPending: sessionLoading, error: sessionError } = useRequireAuth()
  const ownerIdentityRef = useRef<NewResumeOwnerIdentity>({ ownerId: null, generation: 0 })

  if (session && ownerIdentityRef.current.ownerId !== session.user.id) {
    ownerIdentityRef.current = {
      ownerId: session.user.id,
      generation: ownerIdentityRef.current.generation + 1,
    }
  } else if (!session && !sessionLoading && !sessionError && ownerIdentityRef.current.ownerId !== null) {
    ownerIdentityRef.current = {
      ownerId: null,
      generation: ownerIdentityRef.current.generation + 1,
    }
  }

  // Keep an already-authenticated form mounted during a retained-session
  // refresh, but give every confirmed owner a fresh form boundary. This keeps
  // private draft state from ever rendering under a different account.
  if (sessionLoading && !session) {
    return (
      <div className="flex h-[70vh] items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (sessionError && !session) return <SessionLoadError area="New resume" />
  if (!session) return null

  return (
    <NewResumePageForm
      key={session.user.id}
      session={session}
      sessionLoading={sessionLoading}
      ownerIdentityRef={ownerIdentityRef}
    />
  )
}

function NewResumePageForm({
  session,
  sessionLoading,
  ownerIdentityRef,
}: {
  session: NewResumeSession
  sessionLoading: boolean
  ownerIdentityRef: NewResumeOwnerIdentityRef
}) {
  const router = useRouter()

  // ---- form state ----
  const [title, setTitle] = useState('')
  const [mode, setMode] = useState<Mode>('template')
  const [importedContent, setImportedContent] = useState('')
  const [pdfImportFile, setPdfImportFile] = useState<File | null>(null)
  const [linkedinArchiveRequestedAt, setLinkedinArchiveRequestedAt] = useState<string | null>(null)

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
  // Which specific template card is currently being created from — drives a
  // per-card spinner so a slow network doesn't look like a frozen page.
  const [creatingTemplateId, setCreatingTemplateId] = useState<string | null>(null)
  const currentNewResumeIdentityGeneration = ownerIdentityRef.current.generation
  const previewIdentityRef = useRef<TemplatePreviewIdentity>({ templateId: null, generation: 0 })
  const templateUseTokenRef = useRef(0)
  const activeTemplateUseRef = useRef<TemplateUseRequest | null>(null)
  const createTokenRef = useRef(0)
  const activeCreateRef = useRef<CreateRequest | null>(null)
  const mountedRef = useRef(true)

  const isCurrentTemplateUseOwner = useCallback((request: TemplateUseRequest) => {
    const active = activeTemplateUseRef.current
    return mountedRef.current && active?.token === request.token &&
      ownerIdentityRef.current.ownerId === request.ownerId &&
      ownerIdentityRef.current.generation === request.ownerGeneration
  }, [ownerIdentityRef])

  const isCurrentCreateRequest = useCallback((request: CreateRequest) => {
    const active = activeCreateRef.current
    return mountedRef.current && active?.token === request.token &&
      ownerIdentityRef.current.ownerId === request.ownerId &&
      ownerIdentityRef.current.generation === request.ownerGeneration
  }, [ownerIdentityRef])

  useEffect(() => {
    const active = activeTemplateUseRef.current
    if (!active || isCurrentTemplateUseOwner(active)) return
    activeTemplateUseRef.current = null
    setIsCreating(false)
    setCreatingTemplateId(null)
  }, [currentNewResumeIdentityGeneration, isCurrentTemplateUseOwner])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      activeTemplateUseRef.current = null
      activeCreateRef.current = null
      templateUseTokenRef.current += 1
      createTokenRef.current += 1
    }
  }, [])

  useEffect(() => {
    setLinkedinArchiveRequestedAt(readLinkedInArchiveRequest())
  }, [])

  // ---- fetch templates on mount ----
  useEffect(() => {
    if (sessionLoading) return
    if (!session) {
      setLoadingTemplates(false)
      return
    }
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
  }, [session, sessionLoading])

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
      const ia = TEMPLATE_CATEGORY_ORDER.indexOf(a.category)
      const ib = TEMPLATE_CATEGORY_ORDER.indexOf(b.category)
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    }),
  [categories])

  // ---- handlers ----
  const handleUseTemplate = useCallback(async (id: string, preview?: { templateId: string; generation: number }) => {
    if (!mountedRef.current || sessionLoading || activeCreateRef.current || ownerIdentityRef.current.ownerId !== session.user.id) return false
    if (isCreating || activeTemplateUseRef.current) {
      if (creatingTemplateId !== id || activeTemplateUseRef.current) toast('Another template is already being created')
      return false
    }
    const trimmedTitle = title.trim()
    const template = templates.find(t => t.id === id)
    const finalTitle = trimmedTitle || template?.name || 'Untitled Resume'

    setIsCreating(true)
    setCreatingTemplateId(id)
    const request: TemplateUseRequest = {
      token: ++templateUseTokenRef.current,
      ownerId: ownerIdentityRef.current.ownerId,
      ownerGeneration: ownerIdentityRef.current.generation,
      preview,
    }
    activeTemplateUseRef.current = request
    try {
      const result = await apiClient.useTemplate(id, finalTitle)
      if (!isCurrentTemplateUseOwner(request) ||
        (request.preview && (previewIdentityRef.current.templateId !== request.preview.templateId ||
          previewIdentityRef.current.generation !== request.preview.generation))) {
        return false
      }
      toast.success('Resume created from template')
      router.push(`/workspace/${result.resume_id}/edit`)
      return true
    } catch {
      if (isCurrentTemplateUseOwner(request) &&
        (!request.preview || (previewIdentityRef.current.templateId === request.preview.templateId &&
          previewIdentityRef.current.generation === request.preview.generation))) {
        toast.error('Failed to create resume')
      }
      return false
    } finally {
      if (isCurrentTemplateUseOwner(request)) {
        activeTemplateUseRef.current = null
        setIsCreating(false)
        setCreatingTemplateId(null)
      }
    }
  }, [title, templates, router, isCreating, creatingTemplateId, sessionLoading, session.user.id, ownerIdentityRef, isCurrentTemplateUseOwner])

  const handleSelectTemplate = useCallback((id: string) => {
    void handleUseTemplate(id)
  }, [handleUseTemplate])

  const handlePreviewTemplate = useCallback((id: string) => {
    previewIdentityRef.current = {
      templateId: id,
      generation: previewIdentityRef.current.generation + 1,
    }
    setPreviewTemplateId(id)
  }, [])

  const handleClosePreview = useCallback(() => {
    previewIdentityRef.current = {
      templateId: null,
      generation: previewIdentityRef.current.generation + 1,
    }
    setPreviewTemplateId(null)
  }, [])

  const handleUseFromPreview = useCallback((id: string) => {
    const preview = previewIdentityRef.current
    if (preview.templateId !== id) return false
    return handleUseTemplate(id, { templateId: id, generation: preview.generation })
  }, [handleUseTemplate])

  const handleCreate = async () => {
    const ownerId = ownerIdentityRef.current.ownerId
    if (!mountedRef.current || sessionLoading || isCreating || activeCreateRef.current || activeTemplateUseRef.current || ownerId !== session.user.id) return

    const trimmedTitle = title.trim()
    if (!trimmedTitle) {
      toast.error('Please enter a resume title')
      return
    }

    if ((mode === 'import' || mode === 'linkedin' || mode === 'builder') && !importedContent) {
      toast.error('Please upload a file first')
      return
    }

    const request: CreateRequest = {
      token: ++createTokenRef.current,
      ownerId,
      ownerGeneration: ownerIdentityRef.current.generation,
    }
    activeCreateRef.current = request
    setIsCreating(true)
    try {
      if (mode === 'import' || mode === 'linkedin' || mode === 'builder') {
        const created = await apiClient.createResume({
          title: trimmedTitle,
          latex_content: importedContent,
          is_template: false,
        })
        if (!isCurrentCreateRequest(request)) return
        toast.success('Resume created from import')
        router.push(`/workspace/${created.id}/edit`)
      } else {
        // Blank resume
        const created = await apiClient.createResume({
          title: trimmedTitle,
          latex_content: BLANK_CONTENT,
          is_template: false,
        })
        if (!isCurrentCreateRequest(request)) return
        toast.success('Blank resume created')
        router.push(`/workspace/${created.id}/edit`)
      }
    } catch {
      if (isCurrentCreateRequest(request)) toast.error('Failed to create resume')
    } finally {
      if (isCurrentCreateRequest(request)) {
        activeCreateRef.current = null
        setIsCreating(false)
      }
    }
  }

  const canCreate =
    !!title.trim() &&
    !isCreating &&
    ((mode === 'import' || mode === 'linkedin' || mode === 'builder') ? !!importedContent : true)

  // ---------------------------------------------------------------- //
  //  Render                                                           //
  // ---------------------------------------------------------------- //

  if (sessionLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <>
      <div className="content-shell space-y-7 pb-16">
        {/* Header */}
        <header className="flex items-end justify-between gap-4">
          <div>
            <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Workspace</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">Create Resume</h1>
            <p className="mt-1 text-sm text-fg-2">Choose a template or import an existing file.</p>
          </div>
          <Link href="/workspace" className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2">
            Back to Workspace
          </Link>
        </header>

        {/* Title input */}
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
          <label htmlFor="new-resume-title" className="mb-2 block text-xs uppercase tracking-[0.14em] text-fg-3">
            Resume Title
          </label>
          <input
            id="new-resume-title"
            type="text"
            placeholder="Senior Backend Engineer – Q3 2026"
            value={title}
            onChange={e => setTitle(e.target.value)}
            onKeyDown={e => {
              // In template mode there is no single obvious create action — a
              // template still needs to be picked — so Enter must NOT fall
              // through to blank-resume creation. Only trigger create in the
              // import/linkedin/builder flows where one create action exists.
              if (e.key === 'Enter' && mode !== 'template' && canCreate) handleCreate()
            }}
            className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-4 py-3 text-base text-fg outline-none transition focus:border-accent"
          />
        </section>

        <section className="rounded-[var(--radius-lg)] border border-line bg-surface flex flex-col gap-4 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Recommended</p>
            <h2 className="mt-2 flex items-center gap-2 text-xl font-semibold text-fg">
              <Sparkles className="h-4 w-4 text-accent" />
              Guided Builder
            </h2>
            <p className="mt-2 max-w-2xl text-sm text-fg-2">
              Use the new structured builder if you want live preview, section forms, template swapping, and a safer
              path than starting directly in LaTeX.
            </p>
          </div>
          <Link href="/workspace/builder/new" className="rounded-[var(--radius-md)] bg-accent px-5 py-3 text-sm font-semibold text-accent-fg hover:brightness-110">
            Open Guided Builder
          </Link>
        </section>

        {/* Mode toggle */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <button
            onClick={() => { setMode('template'); setImportedContent(''); setPdfImportFile(null) }}
            className={`rounded-[var(--radius-lg)] border border-line bg-surface flex items-start gap-3 p-5 text-left transition ${
              mode === 'template'
                ? 'border-accent bg-accent-soft'
                : 'hover:bg-surface-2'
            }`}
          >
            <LayoutTemplate className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <div>
              <h2 className="text-sm font-semibold text-fg">Use Template</h2>
              <p className="mt-0.5 text-xs text-fg-2">Pick from 50+ LaTeX templates, ready to edit.</p>
            </div>
          </button>

          <button
            onClick={() => { setMode('import'); setImportedContent(''); setPdfImportFile(null) }}
            className={`rounded-[var(--radius-lg)] border border-line bg-surface flex items-start gap-3 p-5 text-left transition ${
              mode === 'import'
                ? 'border-accent bg-accent-soft'
                : 'hover:bg-surface-2'
            }`}
          >
            <Upload className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <div>
              <h2 className="text-sm font-semibold text-fg">Import File</h2>
              <p className="mt-0.5 text-xs text-fg-2">Upload PDF, Word, Markdown, LaTeX, or more.</p>
            </div>
          </button>

          <button
            onClick={() => { setMode('linkedin'); setImportedContent(''); setPdfImportFile(null) }}
            className={`rounded-[var(--radius-lg)] border border-line bg-surface flex items-start gap-3 p-5 text-left transition ${
              mode === 'linkedin'
                ? 'border-accent bg-accent-soft'
                : 'hover:bg-surface-2'
            }`}
          >
            <Linkedin className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <div>
              <h2 className="text-sm font-semibold text-fg">Import from LinkedIn</h2>
              <p className="mt-0.5 text-xs text-fg-2">Export your LinkedIn profile as PDF and import it.</p>
            </div>
          </button>

          <button
            onClick={() => { setMode('builder'); setImportedContent(''); setPdfImportFile(null) }}
            className={`rounded-[var(--radius-lg)] border border-line bg-surface flex items-start gap-3 p-5 text-left transition ${
              mode === 'builder'
                ? 'border-accent bg-accent-soft'
                : 'hover:bg-surface-2'
            }`}
          >
            <PackageOpen className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <div>
              <h2 className="text-sm font-semibold text-fg">Import Builder Export</h2>
              <p className="mt-0.5 text-xs text-fg-2">Bring in Reactive Resume or JSON Resume data, plus PDF and Word exports from Rezi, Teal, and similar tools.</p>
            </div>
          </button>
        </div>

        {/* --- IMPORT MODE --- */}
        {mode === 'import' && (
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
            {pdfImportFile ? <PdfImportWizard file={pdfImportFile} title={title} ownerId={session.user.id}
              onCancel={() => setPdfImportFile(null)}
              onCreated={(resumeId) => {
                if (ownerIdentityRef.current.ownerId === session.user.id) router.push(`/workspace/${encodeURIComponent(resumeId)}/edit`)
              }} /> : <MultiFormatUpload onFileUpload={setImportedContent}
                onPdfSelected={(file) => { setImportedContent(''); setPdfImportFile(file) }} />}
            {importedContent && (
              <p className="mt-3 text-xs uppercase tracking-[0.12em] text-ok">
                File parsed — {importedContent.length.toLocaleString()} characters ready
              </p>
            )}
          </section>
        )}

        {/* --- LINKEDIN MODE --- */}
        {mode === 'linkedin' && (
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-5">
            {/* Step-by-step instructions */}
            <div className="rounded-[var(--radius-md)] border border-accent bg-accent-soft p-4">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-accent-strong">
                <Linkedin className="h-3.5 w-3.5" />
                How to export your LinkedIn profile
              </h3>
              <ol className="mt-3 space-y-1.5 text-xs text-fg-2">
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[10px] font-bold text-accent-strong">1</span>
                  Go to <span className="text-accent-strong">linkedin.com</span> and open your profile
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[10px] font-bold text-accent-strong">2</span>
                  Click <span className="font-medium text-fg-2">&ldquo;More&rdquo; (•••)</span> under your profile photo
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[10px] font-bold text-accent-strong">3</span>
                  Click <span className="font-medium text-fg-2">&ldquo;Save to PDF&rdquo;</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[10px] font-bold text-accent-strong">4</span>
                  Upload the downloaded PDF below
                </li>
              </ol>
            </div>

            <div className="rounded-[var(--radius-md)] border border-line bg-bg p-4">
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-fg-2">
                Want the richer data archive?
              </h3>
              <p className="mt-2 text-xs leading-relaxed text-fg-3">
                Request it from LinkedIn, then keep moving with the profile PDF above. When the ZIP
                is ready, open a résumé and use Tools → Import top projects → LinkedIn. This browser
                remembers the request step.
              </p>
              <a
                href={LINKEDIN_DATA_EXPORT_URL}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setLinkedinArchiveRequestedAt(rememberLinkedInArchiveRequest())}
                className="mt-3 inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-xs font-semibold text-fg transition hover:bg-surface-2"
              >
                Request archive on LinkedIn
                <ExternalLink size={12} aria-hidden="true" />
              </a>
              {linkedinArchiveRequestedAt && (
                <p className="mt-2 text-[10px] text-ok" role="status">
                  Request step saved on {formatLinkedInArchiveRequestDate(linkedinArchiveRequestedAt)}.
                </p>
              )}
            </div>

            {/* Upload area — PDF only, LinkedIn-optimised prompt */}
            <MultiFormatUpload onFileUpload={setImportedContent} sourceHint="linkedin"
              onPdfSelected={(file) => { setImportedContent(''); setPdfImportFile(file); setMode('import') }} />
            {importedContent && (
              <p className="text-xs uppercase tracking-[0.12em] text-ok">
                Profile parsed — {importedContent.length.toLocaleString()} characters ready
              </p>
            )}
          </section>
        )}

        {/* --- BUILDER MODE --- */}
        {mode === 'builder' && (
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
            {importedContent ? (
              <p className="text-xs uppercase tracking-[0.12em] text-ok">
                Resume imported — {importedContent.length.toLocaleString()} characters ready
              </p>
            ) : (
              <ImportFromBuilderWizard onComplete={setImportedContent}
                onPdfSelected={(file) => { setImportedContent(''); setPdfImportFile(file); setMode('import') }} />
            )}
          </section>
        )}

        {/* --- TEMPLATE MODE --- */}
        {mode === 'template' && (
          <section className="space-y-5">
            {/* Title (mirrors the field at the top of the page) + search bar + blank option.
                Keeping a compact title input right next to the gallery makes it obvious
                the title applies to whichever template gets picked below. */}
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                {/* Title */}
                <div className="relative w-full sm:max-w-xs">
                  <input
                    type="text"
                    placeholder="Resume title (used for the template you pick)"
                    value={title}
                    onChange={e => setTitle(e.target.value)}
                    aria-label="Resume title"
                    title="Applied to whichever template you select below"
                    className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition placeholder:text-fg-3 focus:border-accent"
                  />
                </div>

                {/* Search */}
                <div className="relative w-full sm:max-w-xs">
                  <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-fg-3" />
                  <input
                    type="text"
                    placeholder="Search templates…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="w-full rounded-[var(--radius-md)] border border-line bg-bg py-2 pl-9 pr-9 text-sm text-fg outline-none transition placeholder:text-fg-3 focus:border-accent"
                  />
                  {search && (
                    <button
                      onClick={() => setSearch('')}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-fg-3 hover:text-fg-2"
                    >
                      <X size={13} />
                    </button>
                  )}
                </div>
              </div>

              {/* Blank option */}
              <button
                onClick={handleCreate}
                disabled={isCreating}
                className="shrink-0 rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-medium text-fg-3 transition hover:border-line-2 hover:text-fg-2 disabled:opacity-40"
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
                    ? 'border-accent bg-accent-soft text-accent-strong'
                    : 'border-line text-fg-3 hover:border-line-2 hover:text-fg-2'
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
                      ? 'border-accent bg-accent-soft text-accent-strong'
                      : 'border-line text-fg-3 hover:border-line-2 hover:text-fg-2'
                  }`}
                >
                  {cat.label} ({cat.count})
                </button>
              ))}
            </div>

            {/* Template grid */}
            {loadingTemplates ? (
              /* Skeleton */
              <div role="status" aria-label="Loading templates" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="h-64 animate-pulse rounded-[var(--radius-md)] bg-surface-2" />
                ))}
              </div>
            ) : filteredTemplates.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-16 text-center">
                <p className="text-sm text-fg-3">No templates found</p>
                {search && (
                  <button onClick={() => setSearch('')} className="text-xs text-accent-strong hover:underline">
                    Clear search
                  </button>
                )}
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {filteredTemplates.map(template => (
                  <div key={template.id} className="relative">
                    <TemplateCard
                      template={template}
                      onSelect={handleSelectTemplate}
                      onPreview={handlePreviewTemplate}
                      disabled={creatingTemplateId === template.id}
                    />
                    {creatingTemplateId === template.id && (
                      <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded-[var(--radius-lg)] bg-[color:var(--overlay)] backdrop-blur-[1px]">
                        <Loader2 size={20} className="animate-spin text-accent-strong" />
                        <span className="rounded-full bg-surface px-3 py-1 text-xs font-semibold text-fg shadow-[var(--shadow-2)]">
                          Creating…
                        </span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Create button — shown for non-template creation flows */}
        {(mode === 'import' || mode === 'linkedin' || mode === 'builder') && !(mode === 'import' && pdfImportFile) && (
          <div className="flex items-center justify-end gap-3">
            <button
              onClick={handleCreate}
              disabled={!canCreate}
              className="rounded-[var(--radius-md)] bg-accent px-8 py-3 text-sm font-semibold text-accent-fg hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
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
        onClose={handleClosePreview}
      />
    </>
  )
}
