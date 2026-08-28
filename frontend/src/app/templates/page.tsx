'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search, X } from 'lucide-react'
import { toast } from 'sonner'
import { useSession } from '@/lib/auth-client'

import { apiClient } from '@/lib/api-client'
import type { TemplateResponse, TemplateCategoryCount } from '@/lib/api-client'
import TemplateCard from '@/components/TemplateCard'
import TemplatePreviewModal from '@/components/TemplatePreviewModal'
import { TEMPLATE_CATEGORY_ORDER } from '@/lib/template-categories'

// ------------------------------------------------------------------ //
//  Category tab order                                                 //
// ------------------------------------------------------------------ //

export default function TemplatesPage() {
  const router = useRouter()
  const { data: session, isPending: sessionPending } = useSession()

  const [templates, setTemplates] = useState<TemplateResponse[]>([])
  const [categories, setCategories] = useState<TemplateCategoryCount[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [previewTemplateId, setPreviewTemplateId] = useState<string | null>(null)
  const [usingTemplateId, setUsingTemplateId] = useState<string | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // '/' focuses search, unless the user is already typing in a form field.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== '/') return
      const target = e.target as HTMLElement
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return
      e.preventDefault()
      searchInputRef.current?.focus()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Fetch templates on mount
  useEffect(() => {
    let cancelled = false
    setLoading(true)
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
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  // Filtered templates (client-side)
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
        t.category_label.toLowerCase().includes(q) ||
        t.tags.some(tag => tag.toLowerCase().includes(q))
      )
    }
    return list
  }, [templates, activeCategory, search])

  // Sorted category tabs
  const sortedCategories = useMemo(() =>
    [...categories].sort((a, b) => {
      const ia = TEMPLATE_CATEGORY_ORDER.indexOf(a.category)
      const ib = TEMPLATE_CATEGORY_ORDER.indexOf(b.category)
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    }),
  [categories])

  const handlePreview = useCallback((id: string) => {
    setPreviewTemplateId(id)
  }, [])

  const handleUseTemplate = useCallback(async (id: string) => {
    if (sessionPending) return false
    if (usingTemplateId) {
      if (usingTemplateId !== id) toast('Another template is already being created')
      return false
    }
    if (!session) {
      toast('Sign in to use templates')
      const dest = `/templates?use=${id}`
      router.push(`/login?redirect=${encodeURIComponent(dest)}`)
      return false
    }
    setUsingTemplateId(id)
    try {
      const result = await apiClient.useTemplate(id)
      toast.success('Document created from template')
      router.push(`/workspace/${result.resume_id}/edit`)
      return true
    } catch {
      toast.error('Failed to create resume from template')
      return false
    } finally {
      setUsingTemplateId(null)
    }
  }, [session, sessionPending, router, usingTemplateId])

  // The modal awaits this and shows its own "Creating…" state, then closes
  // itself via onClose (success navigates away, unmounting it).
  const handleUseFromPreview = useCallback((id: string) => handleUseTemplate(id), [handleUseTemplate])

  // Resume the "Use Template" flow after returning from login (?use=<id>).
  const [autoUseHandled, setAutoUseHandled] = useState(false)
  useEffect(() => {
    if (autoUseHandled || loading || sessionPending) return
    const useId = new URLSearchParams(window.location.search).get('use')
    if (!useId) return
    setAutoUseHandled(true)
    router.replace('/templates')
    if (session) handleUseTemplate(useId)
  }, [autoUseHandled, loading, session, sessionPending, router, handleUseTemplate])

  const tabClass = (isActive: boolean) =>
    `inline-flex min-h-[36px] items-center rounded-[var(--radius-pill)] border px-4 py-1.5 font-ui text-xs uppercase tracking-[0.08em] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none ${
      isActive
        ? 'border-accent bg-accent-soft text-accent-strong'
        : 'border-line text-fg-3 hover:border-line-2 hover:text-fg'
    }`

  return (
    <>
      <div className="bg-bg text-fg">
        <div className="mx-auto max-w-6xl px-5 py-12 sm:px-8 lg:py-16">
          {/* Header */}
          <header>
            <p className="font-ui text-xs uppercase tracking-[0.18em] text-fg-3">Library</p>
            <h1 className="mt-4 max-w-[18ch] text-balance font-display text-[clamp(2.4rem,6vw,4.4rem)] font-semibold leading-[0.98] tracking-[-0.025em] text-fg">
              LaTeX <span className="text-accent">templates</span>, ready to use.
            </h1>
            <p className="mt-6 max-w-[52ch] font-body text-lg text-fg-2">
              Browse professional résumé, academic, and presentation templates. Preview any
              template, then use it to start building.
            </p>
          </header>

          {/* Search + count */}
          <div className="mt-10 flex flex-col gap-4 border-t border-line pt-6 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full sm:max-w-xs">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-3" />
              <label htmlFor="template-search" className="sr-only">Search templates</label>
              <input
                ref={searchInputRef}
                id="template-search"
                type="text"
                placeholder="Search templates… (press /)"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface py-2.5 pl-9 pr-10 font-body text-sm text-fg outline-none transition duration-150 placeholder:text-fg-3 focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
              />
              {search && (
                <button
                  type="button"
                  aria-label="Clear search"
                  onClick={() => setSearch('')}
                  className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-[var(--radius-sm)] text-fg-3 transition duration-150 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent motion-reduce:transition-none"
                >
                  <X size={14} />
                </button>
              )}
            </div>
            <p className="font-ui text-xs uppercase tracking-[0.12em] text-fg-3" role="status" aria-live="polite">
              {filteredTemplates.length} template{filteredTemplates.length !== 1 ? 's' : ''}
            </p>
          </div>

          {/* Category tabs */}
          <div className="mt-5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveCategory('all')}
              className={tabClass(activeCategory === 'all')}
            >
              All ({templates.length})
            </button>
            {sortedCategories.map(cat => (
              <button
                key={cat.category}
                type="button"
                onClick={() => setActiveCategory(cat.category)}
                className={tabClass(activeCategory === cat.category)}
              >
                {cat.label} ({cat.count})
              </button>
            ))}
          </div>

          {/* Template grid */}
          <div className="mt-10">
            {loading ? (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {Array.from({ length: 12 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-64 rounded-[var(--radius-lg)] border border-line bg-surface-2 motion-safe:animate-pulse"
                  />
                ))}
              </div>
            ) : filteredTemplates.length === 0 ? (
              <div className="flex flex-col items-center gap-3 border-t border-line py-20 text-center" role="status" aria-live="polite">
                <p className="font-body text-sm text-fg-2">No templates found</p>
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch('')}
                    className="font-ui text-xs uppercase tracking-[0.08em] text-accent-strong transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
                  >
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
                      onSelect={handleUseTemplate}
                      onPreview={handlePreview}
                      disabled={usingTemplateId === template.id}
                    />
                    {usingTemplateId === template.id && (
                      <div className="absolute inset-0 z-10 flex items-center justify-center rounded-[var(--radius-lg)] bg-bg/80">
                        <div className="flex items-center gap-2 font-ui text-xs uppercase tracking-[0.08em] text-fg">
                          <div className="h-4 w-4 animate-spin rounded-[var(--radius-pill)] border-2 border-line border-t-accent" />
                          Creating…
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <TemplatePreviewModal
        templateId={previewTemplateId}
        onUse={handleUseFromPreview}
        onClose={() => setPreviewTemplateId(null)}
      />
    </>
  )
}
