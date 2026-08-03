'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { FileText, Loader2, Maximize2, Minimize2, RotateCcw, X } from 'lucide-react'
import { DiffEditor } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'
import { apiClient, type LatexCompiler } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'
import PDFPreview from '@/components/PDFPreview'

type Tab = 'diff' | 'pdf'

interface DiffStats {
  added: number
  removed: number
  changed: number
}

interface Props {
  originalLatex: string
  optimizedLatex: string
  onClose: () => void
  /** If provided, shows a "Restore Original" button */
  onRestore?: (latex: string) => void
  /** Pre-compiled PDF URL for the optimized version */
  optimizedPdfUrl?: string
  /** LaTeX compiler used for the optimized version — used when compiling the original */
  compiler?: LatexCompiler
}

export default function CompareModal({
  originalLatex,
  optimizedLatex,
  onClose,
  onRestore,
  optimizedPdfUrl,
  compiler,
}: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('diff')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [diffStats, setDiffStats] = useState<DiffStats | null>(null)

  // PDF tab state
  const [originalCompileJobId, setOriginalCompileJobId] = useState<string | null>(null)
  const [originalPdfUrl, setOriginalPdfUrl] = useState<string | null>(null)
  const [isCompiling, setIsCompiling] = useState(false)
  const [compileError, setCompileError] = useState<string | null>(null)
  const originalPdfUrlRef = useRef<string | null>(null)

  // Scroll sync refs
  const leftWrapperRef = useRef<HTMLDivElement>(null)
  const rightWrapperRef = useRef<HTMLDivElement>(null)

  const diffEditorRef = useRef<editor.IStandaloneDiffEditor | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  const { state: originalStream } = useJobStream(originalCompileJobId)

  // Handle original PDF compile completion
  useEffect(() => {
    if (originalStream.status !== 'completed' || !originalStream.pdfJobId) return
    const fetchPdf = async () => {
      try {
        const blob = await apiClient.downloadPdf(originalStream.pdfJobId!)
        const url = URL.createObjectURL(blob)
        if (originalPdfUrlRef.current) URL.revokeObjectURL(originalPdfUrlRef.current)
        originalPdfUrlRef.current = url
        setOriginalPdfUrl(url)
      } catch {
        setCompileError('Failed to load compiled PDF')
      } finally {
        setIsCompiling(false)
      }
    }
    void fetchPdf()
  }, [originalStream.status, originalStream.pdfJobId])

  useEffect(() => {
    if (originalStream.status === 'failed') {
      setCompileError('Compilation failed. Check your LaTeX source.')
      setIsCompiling(false)
    }
  }, [originalStream.status])

  // Synchronized scroll: left PDF → right PDF
  useEffect(() => {
    if (activeTab !== 'pdf') return
    const leftEl = leftWrapperRef.current?.querySelector<HTMLElement>('[class*="overflow-auto"]')
    const rightEl = rightWrapperRef.current?.querySelector<HTMLElement>('[class*="overflow-auto"]')
    if (!leftEl || !rightEl) return

    const sync = () => {
      const scrollable = leftEl.scrollHeight - leftEl.clientHeight
      if (scrollable <= 0) return
      const ratio = leftEl.scrollTop / scrollable
      rightEl.scrollTop = ratio * (rightEl.scrollHeight - rightEl.clientHeight)
    }

    leftEl.addEventListener('scroll', sync, { passive: true })
    return () => leftEl.removeEventListener('scroll', sync)
  }, [activeTab, originalPdfUrl, optimizedPdfUrl])

  // Clean up diff editor and blob URLs on unmount
  useEffect(() => {
    return () => {
      const ed = diffEditorRef.current
      if (ed) {
        try { ed.setModel(null) } catch { /* already disposed */ }
        diffEditorRef.current = null
      }
      if (originalPdfUrlRef.current) {
        URL.revokeObjectURL(originalPdfUrlRef.current)
        originalPdfUrlRef.current = null
      }
    }
  }, [])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const computeDiffStats = useCallback((ed: editor.IStandaloneDiffEditor) => {
    const changes = ed.getLineChanges()
    if (!changes) return
    let added = 0
    let removed = 0
    for (const change of changes) {
      if (change.modifiedEndLineNumber > 0)
        added += change.modifiedEndLineNumber - change.modifiedStartLineNumber + 1
      if (change.originalEndLineNumber > 0)
        removed += change.originalEndLineNumber - change.originalStartLineNumber + 1
    }
    setDiffStats({ added, removed, changed: changes.length })
  }, [])

  const handleCompileOriginal = async () => {
    setIsCompiling(true)
    setCompileError(null)
    try {
      const res = await apiClient.compileLatex({ latex_content: originalLatex, compiler })
      if (!res.success || !res.job_id) throw new Error(res.message || 'Failed to start compile')
      setOriginalCompileJobId(res.job_id)
    } catch (err) {
      setCompileError(err instanceof Error ? err.message : 'Compile failed')
      setIsCompiling(false)
    }
  }

  const isOriginalLoading =
    isCompiling ||
    originalStream.status === 'queued' ||
    originalStream.status === 'processing'

  const modalClasses = isFullscreen
    ? 'relative flex h-screen w-screen flex-col bg-bg'
    : 'relative flex h-[85vh] w-[95vw] max-w-7xl flex-col rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)]'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] backdrop-blur-sm">
      <div className={modalClasses}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div className="flex items-center gap-4">
            <h2 className="text-sm font-semibold text-fg">Before / After Optimization</h2>

            {/* Tab toggle */}
            <div className="flex items-center gap-1 rounded-[var(--radius-md)] border border-line bg-surface p-0.5">
              <button
                onClick={() => setActiveTab('diff')}
                className={`rounded-[var(--radius-md)] px-3 py-1 text-xs font-medium transition ${
                  activeTab === 'diff'
                    ? 'bg-surface-2 text-fg'
                    : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                LaTeX Diff
              </button>
              <button
                onClick={() => optimizedPdfUrl && setActiveTab('pdf')}
                disabled={!optimizedPdfUrl}
                title={!optimizedPdfUrl ? 'No compiled PDF available for this comparison' : undefined}
                className={`rounded-[var(--radius-md)] px-3 py-1 text-xs font-medium transition ${
                  activeTab === 'pdf'
                    ? 'bg-surface-2 text-fg'
                    : optimizedPdfUrl
                      ? 'text-fg-3 hover:text-fg-2'
                      : 'cursor-not-allowed text-fg-3'
                }`}
              >
                PDF Preview
              </button>
            </div>

            {activeTab === 'diff' && diffStats && (
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-ok">+{diffStats.added}</span>
                <span className="text-err">−{diffStats.removed}</span>
                <span className="text-fg-3">·</span>
                <span className="text-fg-3">
                  {diffStats.changed} section{diffStats.changed !== 1 ? 's' : ''} changed
                </span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            {onRestore && (
              <button
                onClick={() => onRestore(originalLatex)}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs text-fg-2 transition hover:border-line-2 hover:text-fg"
              >
                <RotateCcw size={12} />
                Restore Original
              </button>
            )}
            <button
              type="button"
              onClick={() => setIsFullscreen((v) => !v)}
              className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            >
              {isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
            <button
              onClick={onClose}
              className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Column labels */}
        <div className="grid grid-cols-2 border-b border-line text-[11px]">
          <div className="truncate border-r border-line px-4 py-1.5 text-fg-3">
            Before Optimization
          </div>
          <div className="truncate px-4 py-1.5 text-fg-3">After Optimization</div>
        </div>

        {/* Content */}
        <div className="relative min-h-0 flex-1 overflow-hidden">
          {/* LaTeX Diff tab */}
          {activeTab === 'diff' && (
            <DiffEditor
              original={originalLatex}
              modified={optimizedLatex}
              language="latex"
              theme="vs-dark"
              onMount={(ed) => {
                diffEditorRef.current = ed
                ed.onDidUpdateDiff(() => computeDiffStats(ed))
              }}
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 12,
                lineNumbers: 'on',
                renderSideBySide: true,
                scrollBeyondLastLine: false,
                wordWrap: 'on',
              }}
            />
          )}

          {/* PDF Preview tab */}
          {activeTab === 'pdf' && (
            <div className="grid h-full grid-cols-2 divide-x divide-line">
              {/* Left: Before (original — needs compile) */}
              <div ref={leftWrapperRef} className="flex h-full flex-col overflow-hidden">
                {!originalPdfUrl && !isOriginalLoading && (
                  <div className="flex h-full flex-col items-center justify-center gap-3 bg-surface-2">
                    <FileText className="h-9 w-9 text-fg-3" />
                    <p className="text-xs text-fg-3">Original PDF not compiled yet</p>
                    {compileError && (
                      <p className="max-w-[220px] text-center text-[11px] text-err">{compileError}</p>
                    )}
                    <button
                      onClick={handleCompileOriginal}
                      className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-accent bg-accent-soft px-4 py-2 text-xs font-semibold text-accent-strong transition hover:brightness-110"
                    >
                      Compile Original
                    </button>
                  </div>
                )}
                {isOriginalLoading && (
                  <div className="flex h-full flex-col items-center justify-center gap-3 bg-surface-2">
                    <Loader2 className="h-6 w-6 animate-spin text-accent-strong" />
                    <p className="text-xs text-fg-3">
                      {originalStream.stage || 'Compiling…'}
                    </p>
                    {originalStream.percent > 0 && (
                      <div className="h-1 w-40 overflow-hidden rounded-full bg-surface-2">
                        <div
                          className="h-full rounded-full bg-accent transition-all"
                          style={{ width: `${originalStream.percent}%` }}
                        />
                      </div>
                    )}
                  </div>
                )}
                {originalPdfUrl && !isOriginalLoading && (
                  <PDFPreview
                    pdfUrl={originalPdfUrl}
                    isLoading={false}
                    onDownload={() => {
                      const a = document.createElement('a')
                      a.href = originalPdfUrl
                      a.download = 'original_resume.pdf'
                      a.click()
                    }}
                  />
                )}
              </div>

              {/* Right: After (optimized) */}
              <div ref={rightWrapperRef} className="flex h-full flex-col overflow-hidden">
                <PDFPreview
                  pdfUrl={optimizedPdfUrl ?? null}
                  isLoading={false}
                  onDownload={
                    optimizedPdfUrl
                      ? () => {
                          const a = document.createElement('a')
                          a.href = optimizedPdfUrl
                          a.download = 'optimized_resume.pdf'
                          a.click()
                        }
                      : undefined
                  }
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
