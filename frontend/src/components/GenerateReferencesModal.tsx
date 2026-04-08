'use client'

import { useCallback, useState } from 'react'
import { BookUser, Download, Loader2, Plus, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ReferenceContact } from '@/lib/api-client'

interface GenerateReferencesModalProps {
  isOpen: boolean
  onClose: () => void
  resumeId: string
  resumeTitle: string
}

const EMPTY_CONTACT = (): ReferenceContact => ({
  name: '',
  title: '',
  company: '',
  email: '',
  phone: '',
  relationship: '',
})

export default function GenerateReferencesModal({
  isOpen,
  onClose,
  resumeId,
  resumeTitle,
}: GenerateReferencesModalProps) {
  const [refs, setRefs] = useState<ReferenceContact[]>([EMPTY_CONTACT()])
  const [loading, setLoading] = useState(false)

  const handleAdd = () => {
    if (refs.length >= 5) {
      toast.error('Maximum 5 references allowed')
      return
    }
    setRefs((prev) => [...prev, EMPTY_CONTACT()])
  }

  const handleRemove = (idx: number) => {
    setRefs((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleChange = (idx: number, field: keyof ReferenceContact, value: string) => {
    setRefs((prev) => prev.map((r, i) => (i === idx ? { ...r, [field]: value } : r)))
  }

  const handleGenerate = useCallback(async () => {
    // Validate required fields
    for (let i = 0; i < refs.length; i++) {
      const r = refs[i]
      if (!r.name.trim() || !r.title.trim() || !r.company.trim() || !r.relationship.trim()) {
        toast.error(`Reference ${i + 1}: name, title, company, and relationship are required`)
        return
      }
    }

    setLoading(true)
    try {
      // Strip empty optional fields
      const payload = refs.map((r) => ({
        name: r.name.trim(),
        title: r.title.trim(),
        company: r.company.trim(),
        relationship: r.relationship.trim(),
        email: r.email?.trim() || undefined,
        phone: r.phone?.trim() || undefined,
      }))

      const result = await apiClient.generateReferences(resumeId, payload)

      // Download as .tex file
      const blob = new Blob([result.latex_content], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const safeName = resumeTitle.replace(/[^a-zA-Z0-9_-]/g, '_').replace(/_+/g, '_')
      a.href = url
      a.download = `${safeName}_references.tex`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)

      toast.success('References page downloaded')
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setLoading(false)
    }
  }, [refs, resumeId, resumeTitle, onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-xl rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-violet-500/15">
              <BookUser size={13} className="text-violet-300" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">Generate References Page</h2>
              <p className="text-[10px] text-zinc-600">{resumeTitle}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto p-4">
          <p className="mb-4 text-[12px] text-zinc-500">
            Add up to 5 references. The LaTeX will match your resume&apos;s document class and style.
          </p>

          <div className="space-y-4">
            {refs.map((ref, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3"
              >
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    Reference {idx + 1}
                  </span>
                  {refs.length > 1 && (
                    <button
                      onClick={() => handleRemove(idx)}
                      className="rounded p-1 text-zinc-700 transition hover:bg-white/[0.06] hover:text-rose-400"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div className="col-span-2">
                    <input
                      type="text"
                      placeholder="Full name *"
                      value={ref.name}
                      onChange={(e) => handleChange(idx, 'name', e.target.value)}
                      className="w-full rounded-md border border-white/[0.08] bg-black/30 px-2.5 py-1.5 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none transition focus:border-white/[0.15]"
                    />
                  </div>
                  <input
                    type="text"
                    placeholder="Job title *"
                    value={ref.title}
                    onChange={(e) => handleChange(idx, 'title', e.target.value)}
                    className="rounded-md border border-white/[0.08] bg-black/30 px-2.5 py-1.5 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none transition focus:border-white/[0.15]"
                  />
                  <input
                    type="text"
                    placeholder="Company *"
                    value={ref.company}
                    onChange={(e) => handleChange(idx, 'company', e.target.value)}
                    className="rounded-md border border-white/[0.08] bg-black/30 px-2.5 py-1.5 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none transition focus:border-white/[0.15]"
                  />
                  <input
                    type="text"
                    placeholder="Relationship (e.g. Direct Manager) *"
                    value={ref.relationship}
                    onChange={(e) => handleChange(idx, 'relationship', e.target.value)}
                    className="col-span-2 rounded-md border border-white/[0.08] bg-black/30 px-2.5 py-1.5 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none transition focus:border-white/[0.15]"
                  />
                  <input
                    type="email"
                    placeholder="Email (optional)"
                    value={ref.email ?? ''}
                    onChange={(e) => handleChange(idx, 'email', e.target.value)}
                    className="rounded-md border border-white/[0.08] bg-black/30 px-2.5 py-1.5 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none transition focus:border-white/[0.15]"
                  />
                  <input
                    type="tel"
                    placeholder="Phone (optional)"
                    value={ref.phone ?? ''}
                    onChange={(e) => handleChange(idx, 'phone', e.target.value)}
                    className="rounded-md border border-white/[0.08] bg-black/30 px-2.5 py-1.5 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none transition focus:border-white/[0.15]"
                  />
                </div>
              </div>
            ))}
          </div>

          {refs.length < 5 && (
            <button
              onClick={handleAdd}
              className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-white/[0.08] py-2 text-xs font-medium text-zinc-600 transition hover:border-white/[0.14] hover:text-zinc-400"
            >
              <Plus size={12} />
              Add reference
            </button>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 border-t border-white/[0.06] px-4 py-3">
          <button
            onClick={onClose}
            className="flex-1 rounded-lg border border-white/[0.06] py-2 text-xs font-semibold text-zinc-500 transition hover:text-zinc-300"
          >
            Cancel
          </button>
          <button
            onClick={handleGenerate}
            disabled={loading}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-violet-500/20 py-2 text-xs font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30 disabled:opacity-50"
          >
            {loading ? (
              <><Loader2 size={12} className="animate-spin" /> Generating…</>
            ) : (
              <><Download size={12} /> Download .tex</>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
