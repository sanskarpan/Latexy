'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Upload, ChevronRight, ChevronLeft, Check, AlertCircle, Loader2, X } from 'lucide-react'
import { apiClient, type ParsePreviewResponse } from '@/lib/api-client'
import { useFormatConversion } from '@/hooks/useFormatConversion'
import { runLatestRequest } from '@/lib/latest-request'

// ── Platform definitions ───────────────────────────────────────────────────────

type PlatformId = 'reactive_resume' | 'json_resume' | 'document_builders' | 'generic'

interface Platform {
  id: PlatformId
  name: string
  description: string
  exportFormat: string
  steps: string[]
  acceptedExtensions: string[]
  color: string
}

const PLATFORMS: Platform[] = [
  {
    id: 'reactive_resume',
    name: 'Reactive Resume',
    description: 'Import a native Reactive Resume v4 or v5 backup',
    exportFormat: 'JSON',
    steps: [
      'Open the resume in Reactive Resume',
      'Use the resume actions menu and choose Export to JSON',
      'Upload the downloaded .json file below',
    ],
    acceptedExtensions: ['.json'],
    color: 'text-accent-strong bg-accent-soft border-accent',
  },
  {
    id: 'json_resume',
    name: 'JSON Resume',
    description: 'Import the open JSON Resume schema used across many tools',
    exportFormat: 'JSON',
    steps: [
      'Export a standards-compatible JSON Resume file from your current tool',
      'Check that the file contains basics, work, education, or skills fields',
      'Upload the .json file below',
    ],
    acceptedExtensions: ['.json'],
    color: 'text-accent-strong bg-accent-soft border-accent',
  },
  {
    id: 'document_builders',
    name: 'Rezi or Teal',
    description: 'Import the PDF or Word document exported by these builders',
    exportFormat: 'PDF / Word',
    steps: [
      'Download your resume from Rezi or Teal as PDF or Word',
      'Use the highest-quality text-based export available',
      'Upload the .pdf or .docx file below',
    ],
    acceptedExtensions: ['.pdf', '.docx', '.doc'],
    color: 'text-accent-strong bg-accent-soft border-accent',
  },
  {
    id: 'generic',
    name: 'Other Builder',
    description: 'Use a JSON Resume, PDF, or Word export from another tool',
    exportFormat: 'JSON / PDF / Word',
    steps: [
      'Export your resume from any builder as JSON Resume, PDF, or Word',
      'Upload the file below',
    ],
    acceptedExtensions: ['.json', '.pdf', '.docx', '.doc'],
    color: 'text-fg-2 bg-surface-2 border-line',
  },
]

// ── Sub-components ─────────────────────────────────────────────────────────────

function StepDot({ active, done, n }: { active: boolean; done: boolean; n: number }) {
  return (
    <div
      className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold transition-all ${
        done
          ? 'bg-ok/20 text-ok ring-1 ring-ok/40'
          : active
            ? 'bg-accent-soft text-accent-strong ring-1 ring-accent'
            : 'bg-surface-2 text-fg-3'
      }`}
    >
      {done ? <Check className="h-3 w-3" /> : n}
    </div>
  )
}

function PlatformCard({
  platform,
  selected,
  onClick,
}: {
  platform: Platform
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-start gap-3 rounded-[var(--radius-lg)] border p-4 text-left transition hover:brightness-110 ${
        selected
          ? `${platform.color} ring-1 ring-current/30`
          : 'border-line bg-surface hover:bg-surface-2'
      }`}
    >
      <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-md)] text-xs font-bold ${selected ? platform.color : 'bg-surface-2 text-fg-3'}`}>
        {platform.name[0]}
      </div>
      <div>
        <p className="text-sm font-semibold text-fg">{platform.name}</p>
        <p className="mt-0.5 text-xs text-fg-3">{platform.description}</p>
        <p className={`mt-1 text-[10px] font-medium ${selected ? '' : 'text-fg-3'}`}>
          {platform.exportFormat}
        </p>
      </div>
      {selected && <Check className="ml-auto mt-0.5 h-4 w-4 shrink-0 text-ok" />}
    </button>
  )
}

// ── Wizard ─────────────────────────────────────────────────────────────────────

interface ImportFromBuilderWizardProps {
  onComplete: (latexContent: string) => void
  onPdfSelected?: (file: File) => void
}

type Step = 1 | 2 | 3 | 4

export default function ImportFromBuilderWizard({ onComplete, onPdfSelected }: ImportFromBuilderWizardProps) {
  const [step, setStep] = useState<Step>(1)
  const [platform, setPlatform] = useState<Platform | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ParsePreviewResponse | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const previewRequestRef = useRef(0)

  const { status, progress, convertedLatex, error: conversionError, startConversion, reset: resetConversion } = useFormatConversion()

  // Handle async job completing — call onComplete when latex becomes available
  useEffect(() => {
    if (status === 'done' && convertedLatex) {
      onComplete(convertedLatex)
    }
  }, [status, convertedLatex, onComplete])

  const STEPS = ['Platform', 'Instructions', 'Upload', 'Preview']

  const invalidatePreviewRequest = useCallback(() => {
    previewRequestRef.current += 1
    setPreviewLoading(false)
  }, [])

  useEffect(() => () => {
    previewRequestRef.current += 1
  }, [])

  const handleFileSelect = useCallback(async (selectedFile: File) => {
    if (onPdfSelected && selectedFile.name.toLowerCase().endsWith('.pdf')) {
      previewRequestRef.current += 1
      resetConversion()
      onPdfSelected(selectedFile)
      return
    }
    const requestId = ++previewRequestRef.current
    setFile(selectedFile)
    setPreview(null)
    setPreviewError(null)
    setPreviewLoading(true)
    await runLatestRequest(
      () => apiClient.parseForPreview(selectedFile),
      () => requestId === previewRequestRef.current,
      (result) => {
        setPreview(result)
        setStep(4)
      },
      (err) => {
        const msg = err instanceof Error ? err.message : 'Failed to parse file'
        setPreviewError(msg.includes('422') ? 'File could not be parsed — check it is not corrupted' : msg)
        setStep(4)
      },
      () => setPreviewLoading(false),
    )
  }, [onPdfSelected, resetConversion])

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setDragOver(false)
      const dropped = e.dataTransfer.files[0]
      if (dropped) handleFileSelect(dropped)
    },
    [handleFileSelect],
  )

  const handleConvert = useCallback(async () => {
    if (!file) return
    resetConversion()
    const sourcePlatform = platform?.id === 'reactive_resume' ? platform.id : undefined
    // onComplete is called by the useEffect above when status transitions to 'done'.
    // We do NOT call it here to avoid double-invocation.
    await startConversion(file, undefined, sourcePlatform)
  }, [file, platform, startConversion, resetConversion])

  const converting = status === 'uploading' || status === 'converting'

  return (
    <div className="space-y-5">
      {/* Progress bar */}
      <div className="flex items-center gap-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <StepDot active={step === i + 1} done={step > i + 1} n={i + 1} />
              <span className={`hidden text-[11px] sm:inline ${step === i + 1 ? 'text-fg-2' : step > i + 1 ? 'text-ok' : 'text-fg-3'}`}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={`h-px w-6 rounded ${step > i + 1 ? 'bg-ok/30' : 'bg-surface-2'}`} />
            )}
          </div>
        ))}
      </div>

      {/* ── Step 1: Platform selector ── */}
      {step === 1 && (
        <div className="space-y-4">
          <p className="text-xs text-fg-3">Which resume builder are you importing from?</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {PLATFORMS.map((p) => (
              <PlatformCard
                key={p.id}
                platform={p}
                selected={platform?.id === p.id}
                onClick={() => setPlatform(p)}
              />
            ))}
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              disabled={!platform}
              onClick={() => setStep(2)}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-xs font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
            >
              Next <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* ── Step 2: Export instructions ── */}
      {step === 2 && platform && (
        <div className="space-y-4">
          <div className={`rounded-[var(--radius-lg)] border p-4 ${platform.color}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.12em]">
              How to export from {platform.name}
            </p>
            <ol className="mt-3 space-y-2">
              {platform.steps.map((s, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-fg-2">
                  <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${platform.color}`}>
                    {i + 1}
                  </span>
                  {s}
                </li>
              ))}
            </ol>
          </div>
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-4 py-2 text-xs text-fg-3 transition hover:text-fg-2"
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Back
            </button>
            <button
              type="button"
              onClick={() => setStep(3)}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-xs font-medium text-accent-strong transition hover:brightness-110"
            >
              Next <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* ── Step 3: File upload ── */}
      {step === 3 && platform && (
        <div className="space-y-4">
          <p className="text-xs text-fg-3">
            Drop your {platform.exportFormat} file below ({platform.acceptedExtensions.join(', ')})
          </p>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center gap-3 rounded-[var(--radius-lg)] border-2 border-dashed p-8 text-center transition ${
              dragOver
                ? 'border-accent bg-accent-soft'
                : 'border-line hover:border-line-2 hover:bg-surface-2'
            }`}
          >
            <Upload className="h-8 w-8 text-fg-3" />
            <div>
              <p className="text-sm font-medium text-fg-2">Drop file here or click to browse</p>
              <p className="mt-1 text-xs text-fg-3">{platform.acceptedExtensions.join(', ')} · max 10 MB</p>
            </div>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept={platform.acceptedExtensions.join(',')}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleFileSelect(f)
            }}
          />
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => { invalidatePreviewRequest(); setStep(2) }}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-4 py-2 text-xs text-fg-3 transition hover:text-fg-2"
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Back
            </button>
          </div>
        </div>
      )}

      {/* ── Step 4: Preview + convert ── */}
      {step === 4 && file && (
        <div className="space-y-4">
          {previewLoading && (
            <div className="flex items-center gap-2 text-xs text-fg-3">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Parsing file…
            </div>
          )}

          {!previewLoading && previewError && (
            <div className="flex items-start gap-2 rounded-[var(--radius-md)] border border-err/20 bg-err/5 p-3 text-xs text-err">
              <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" />
              {previewError}
            </div>
          )}

          {!previewLoading && preview && (
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 space-y-3">
              <p className="text-[10px] uppercase tracking-widest text-fg-3">Parsed preview</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {preview.name && (
                  <div>
                    <span className="text-fg-3">Name</span>
                    <p className="mt-0.5 font-medium text-fg">{preview.name}</p>
                  </div>
                )}
                {preview.email && (
                  <div>
                    <span className="text-fg-3">Email</span>
                    <p className="mt-0.5 font-medium text-fg">{preview.email}</p>
                  </div>
                )}
                <div>
                  <span className="text-fg-3">Experience</span>
                  <p className="mt-0.5 font-medium text-fg">{preview.experience_count} {preview.experience_count === 1 ? 'entry' : 'entries'}</p>
                </div>
                <div>
                  <span className="text-fg-3">Education</span>
                  <p className="mt-0.5 font-medium text-fg">{preview.education_count} {preview.education_count === 1 ? 'entry' : 'entries'}</p>
                </div>
              </div>
              {preview.skills.length > 0 && (
                <div>
                  <p className="text-[10px] text-fg-3">Skills</p>
                  <p className="mt-0.5 text-xs text-fg-2">{preview.skills.join(', ')}</p>
                </div>
              )}
            </div>
          )}

          {/* File info */}
          {!previewLoading && (
            <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg-2">
              <Upload className="h-3.5 w-3.5 shrink-0 text-fg-3" />
              <span className="flex-1 truncate">{file.name}</span>
              <button
                type="button"
                onClick={() => { invalidatePreviewRequest(); setFile(null); setPreview(null); setPreviewError(null); setStep(3) }}
                className="shrink-0 text-fg-3 hover:text-fg-2"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}

          {/* Conversion progress */}
          {converting && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 text-xs text-fg-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {status === 'uploading' ? 'Uploading…' : `Converting to LaTeX… ${progress}%`}
              </div>
              {status === 'converting' && (
                <div className="h-1 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className="h-full rounded-full bg-accent transition-all duration-500"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              )}
            </div>
          )}

          {conversionError && (
            <div className="flex items-start gap-2 rounded-[var(--radius-md)] border border-err/20 bg-err/5 p-3 text-xs text-err">
              <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" />
              {conversionError}
            </div>
          )}

          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => { invalidatePreviewRequest(); resetConversion(); setStep(3) }}
              disabled={converting}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-4 py-2 text-xs text-fg-3 transition hover:text-fg-2 disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Back
            </button>
            <button
              type="button"
              onClick={handleConvert}
              disabled={converting || previewLoading || !file}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-xs font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
            >
              {converting ? (
                <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Converting…</>
              ) : (
                <>Convert to LaTeX <ChevronRight className="h-3.5 w-3.5" /></>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
