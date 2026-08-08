'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { ChevronLeft, ChevronRight, Merge, Check, Loader2, FileText } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ResumeResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'

function parseLatexSections(latex: string): string[] {
  const matches = latex.matchAll(/\\section\*?\{([^}]+)\}/g)
  const names: string[] = []
  for (const m of matches) {
    if (!names.includes(m[1])) names.push(m[1])
  }
  return names
}

export default function MergeResumesPage() {
  const { data: session, isPending } = useSession()
  const router = useRouter()

  const [step, setStep] = useState<1 | 2 | 3 | 4>(1)
  const [resumes, setResumes] = useState<ResumeResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])
  const [sectionChoices, setSectionChoices] = useState<Record<string, string>>({})
  const [detectedSections, setDetectedSections] = useState<Record<string, string[]>>({})
  const [merging, setMerging] = useState(false)
  const [mergedLatex, setMergedLatex] = useState('')
  const [newResumeId, setNewResumeId] = useState('')
  const mergeCalledRef = useRef(false)

  // Auth guard
  useEffect(() => {
    if (!isPending && !session) {
      router.push('/login')
    }
  }, [isPending, session, router])

  // Fetch resumes on mount
  useEffect(() => {
    if (!session) return
    setLoading(true)
    apiClient
      .listResumes()
      .then(setResumes)
      .catch(() => toast.error('Failed to load resumes'))
      .finally(() => setLoading(false))
  }, [session])

  // Compute detected sections when entering step 2
  useEffect(() => {
    if (step !== 2) return
    const selectedResumes = resumes.filter(r => selected.includes(r.id))
    const sections: Record<string, string[]> = {}
    for (const r of selectedResumes) {
      sections[r.id] = parseLatexSections(r.latex_content)
    }
    setDetectedSections(sections)

    // Set default section choices — all sections default to first selected resume
    const allSections = Array.from(
      new Set(Object.values(sections).flat())
    )
    const defaults: Record<string, string> = {}
    for (const sec of allSections) {
      defaults[sec] = selected[0]
    }
    setSectionChoices(prev => {
      // Preserve any already-set choices, only set defaults for new ones
      const merged: Record<string, string> = { ...defaults }
      for (const [k, v] of Object.entries(prev)) {
        if (k in merged) merged[k] = v
      }
      return merged
    })
  }, [step, resumes, selected])

  // Run merge API call once when entering step 3
  useEffect(() => {
    if (step !== 3) return
    if (mergeCalledRef.current) return
    mergeCalledRef.current = true

    setMerging(true)
    apiClient
      .mergeResumes(selected, sectionChoices)
      .then(result => {
        setMergedLatex(result.merged_latex)
        setNewResumeId(result.new_resume_id)
      })
      .catch(err => {
        toast.error(err?.message ?? 'Merge failed. Please try again.')
        mergeCalledRef.current = false
        setStep(2)
      })
      .finally(() => setMerging(false))
  }, [step, selected, sectionChoices])

  function toggleSelect(id: string) {
    setSelected(prev => {
      if (prev.includes(id)) return prev.filter(x => x !== id)
      if (prev.length >= 4) return prev
      return [...prev, id]
    })
  }

  function goToStep2() {
    setStep(2)
  }

  function goToStep3() {
    setStep(3)
  }

  function goBackToStep2() {
    mergeCalledRef.current = false
    setStep(2)
  }

  function saveResume() {
    setStep(4)
  }

  const allSections = Array.from(new Set(Object.values(detectedSections).flat()))

  if (isPending || loading) {
    return (
      <div className="content-shell flex items-center justify-center py-24">
        <Loader2 className="animate-spin text-accent-strong" size={28} />
      </div>
    )
  }

  return (
    <div className="content-shell space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/workspace" className="text-fg-3 hover:text-fg-2">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Workspace</p>
          <h1 className="text-2xl font-semibold text-fg flex items-center gap-2">
            <Merge size={20} className="text-accent-strong" />
            Merge Resumes
          </h1>
        </div>
      </div>

      {/* Step indicator */}
      <div className="flex gap-2">
        {[1, 2, 3, 4].map(n => (
          <div
            key={n}
            className={`h-1 flex-1 rounded-full ${step >= n ? 'bg-accent' : 'bg-surface-2'}`}
          />
        ))}
      </div>

      {/* Step content */}
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">

        {/* ── Step 1: Select Resumes ── */}
        {step === 1 && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-fg">Step 1 of 4 — Select Resumes</h2>
              <p className="mt-1 text-sm text-fg-2">Choose 2 to 4 resumes to merge</p>
            </div>

            <div className="flex items-center gap-2">
              <span className="rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-semibold text-accent-strong border border-accent">
                {selected.length} selected
              </span>
              {selected.length >= 4 && (
                <span className="text-xs text-fg-3">Maximum of 4 resumes reached</span>
              )}
            </div>

            {resumes.length === 0 ? (
              <div className="flex flex-col items-center gap-3 py-12 text-fg-3">
                <FileText size={32} />
                <p className="text-sm">No resumes found. Create some resumes first.</p>
                <Link href="/workspace/new" className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110">
                  Create Resume
                </Link>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {resumes.map(resume => {
                  const isSelected = selected.includes(resume.id)
                  const isDisabled = !isSelected && selected.length >= 4
                  return (
                    <button
                      key={resume.id}
                      onClick={() => !isDisabled && toggleSelect(resume.id)}
                      disabled={isDisabled}
                      className={`flex items-start gap-3 rounded-[var(--radius-md)] border p-4 text-left transition ${
                        isSelected
                          ? 'border-accent bg-accent-soft'
                          : isDisabled
                            ? 'cursor-not-allowed border-line bg-surface-2/40 opacity-40'
                            : 'border-line bg-surface-2 hover:border-line-2 hover:bg-surface-2'
                      }`}
                    >
                      <div
                        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition ${
                          isSelected
                            ? 'border-accent bg-accent'
                            : 'border-line-2 bg-transparent'
                        }`}
                      >
                        {isSelected && <Check size={10} className="text-accent-fg" strokeWidth={3} />}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-fg">{resume.title}</p>
                        <p className="mt-0.5 text-xs text-fg-3">
                          Updated {new Date(resume.updated_at).toLocaleDateString()}
                        </p>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}

            <div className="flex justify-end">
              <button
                onClick={goToStep2}
                disabled={selected.length < 2}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-5 py-2.5 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Choose Sections ── */}
        {step === 2 && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-fg">Step 2 of 4 — Choose Sections</h2>
              <p className="mt-1 text-sm text-fg-2">
                For each section, pick which resume&apos;s version to use
              </p>
            </div>

            {allSections.length === 0 ? (
              <p className="text-sm text-fg-3 py-4">
                No sections detected in the selected resumes.
              </p>
            ) : (
              <div className="space-y-3">
                {allSections.map(section => (
                  <div
                    key={section}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-line bg-surface-2 px-4 py-3"
                  >
                    <span className="text-sm font-medium text-fg">{section}</span>
                    <select
                      value={sectionChoices[section] ?? selected[0]}
                      onChange={e =>
                        setSectionChoices(prev => ({ ...prev, [section]: e.target.value }))
                      }
                      className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-1.5 text-xs text-fg outline-none transition focus:border-accent"
                    >
                      {selected.map(id => {
                        const r = resumes.find(x => x.id === id)
                        return (
                          <option key={id} value={id}>
                            {r?.title ?? id}
                          </option>
                        )
                      })}
                    </select>
                  </div>
                ))}
              </div>
            )}

            <div className="flex justify-between">
              <button
                onClick={() => setStep(1)}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-sm text-fg transition hover:bg-surface-2"
              >
                <ChevronLeft size={15} />
                Back
              </button>
              <button
                onClick={goToStep3}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-5 py-2.5 text-sm font-semibold text-accent-fg transition hover:brightness-110"
              >
                Next
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Preview ── */}
        {step === 3 && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-fg">Step 3 of 4 — Preview</h2>
              <p className="mt-1 text-sm text-fg-2">
                Merged result combines sections from {selected.length} resumes
              </p>
            </div>

            {merging ? (
              <div className="flex flex-col items-center gap-4 py-16">
                <Loader2 className="animate-spin text-accent-strong" size={32} />
                <p className="text-sm text-fg-2">Merging resumes…</p>
              </div>
            ) : (
              <textarea
                readOnly
                value={mergedLatex}
                rows={24}
                className="w-full resize-y rounded-[var(--radius-md)] border border-line bg-bg px-4 py-3 font-mono text-xs text-fg-2 outline-none"
              />
            )}

            <div className="flex justify-between">
              <button
                onClick={goBackToStep2}
                disabled={merging}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-sm text-fg transition hover:bg-surface-2 disabled:opacity-40"
              >
                <ChevronLeft size={15} />
                Back
              </button>
              <button
                onClick={saveResume}
                disabled={merging || !mergedLatex}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-5 py-2.5 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Save as New Resume
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 4: Done ── */}
        {step === 4 && (
          <div className="flex flex-col items-center gap-6 py-12 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-ok/15">
              <Check size={32} className="text-ok" />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-fg">Merged Resume Saved!</h2>
              <p className="mt-1 text-sm text-fg-2">Your new resume has been created successfully.</p>
            </div>
            <div className="flex flex-wrap justify-center gap-3">
              <Link
                href={`/workspace/${newResumeId}/edit`}
                className="rounded-[var(--radius-md)] bg-accent px-5 py-2.5 text-sm font-semibold text-accent-fg transition hover:brightness-110"
              >
                Open Resume
              </Link>
              <Link
                href="/workspace"
                className="rounded-[var(--radius-md)] border border-line-2 px-5 py-2.5 text-sm text-fg transition hover:bg-surface-2"
              >
                ← Back to Workspace
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
