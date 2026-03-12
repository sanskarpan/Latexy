'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search, X } from 'lucide-react'
import { toast } from 'sonner'
import { useSession } from '@/lib/auth-client'

import { apiClient } from '@/lib/api-client'
import type { TemplateResponse, TemplateCategoryCount } from '@/lib/api-client'
import TemplateCard from '@/components/TemplateCard'
import TemplatePreviewModal from '@/components/TemplatePreviewModal'

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

export default function TemplatesPage() {
  const router = useRouter()
  const { data: session } = useSession()

  const [templates, setTemplates] = useState<TemplateResponse[]>([])
  const [categories, setCategories] = useState<TemplateCategoryCount[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [previewTemplateId, setPreviewTemplateId] = useState<string | null>(null)
  const [usingTemplateId, setUsingTemplateId] = useState<string | null>(null)

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
        t.tags.some(tag => tag.toLowerCase().includes(q))
      )
    }
    return list
  }, [templates, activeCategory, search])

  // Sorted category tabs
  const sortedCategories = useMemo(() =>
    [...categories].sort((a, b) => {
      const ia = CATEGORY_ORDER.indexOf(a.category)
      const ib = CATEGORY_ORDER.indexOf(b.category)
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    }),
  [categories])

  const handlePreview = useCallback((id: string) => {
    setPreviewTemplateId(id)
  }, [])

  const handleUseTemplate = useCallback(async (id: string) => {
    if (!session) {
      router.push('/login')
      return
    }
    setUsingTemplateId(id)
    try {
      const result = await apiClient.useTemplate(id)
      toast.success('Resume created from template')
      router.push(`/workspace/${result.resume_id}/edit`)
    } catch {
      toast.error('Failed to create resume from template')
    } finally {
      setUsingTemplateId(null)
    }
  }, [session, router])

  const handleUseFromPreview = useCallback((id: string) => {
    setPreviewTemplateId(null)
    handleUseTemplate(id)
  }, [handleUseTemplate])

  return (
    <>
      <div className="content-shell space-y-7 pb-16">
        {/* Header */}
        <header className="pt-2">
          <p className="overline">Library</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">
            Resume Templates
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Browse 50+ professional LaTeX templates across industries. Preview, then use any template to start building.
          </p>
        </header>

        {/* Search + count */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
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
          <p className="text-xs text-zinc-500">
            {filteredTemplates.length} template{filteredTemplates.length !== 1 ? 's' : ''}
          </p>
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
        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 12 }).map((_, i) => (
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
                onSelect={handleUseTemplate}
                onPreview={handlePreview}
              />
            ))}
          </div>
        )}
      </div>

      <TemplatePreviewModal
        templateId={previewTemplateId}
        onUse={handleUseFromPreview}
        onClose={() => setPreviewTemplateId(null)}
      />
    </>
  )
}
