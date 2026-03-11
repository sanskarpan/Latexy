'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Download, ChevronDown, Loader2, FileText, Code, File, Globe, Database } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'

const EXPORT_FORMATS = [
  { key: 'pdf',  label: 'PDF',        icon: FileText, desc: 'Compiled PDF document' },
  { key: 'tex',  label: 'LaTeX',      icon: Code,     desc: 'LaTeX source code (.tex)' },
  { key: 'docx', label: 'Word',       icon: FileText, desc: 'Microsoft Word (.docx)' },
  { key: 'md',   label: 'Markdown',   icon: File,     desc: 'Markdown (.md)' },
  { key: 'html', label: 'HTML',       icon: Globe,    desc: 'Web page (.html)' },
  { key: 'txt',  label: 'Plain Text', icon: File,     desc: 'ATS-safe plain text (.txt)' },
  { key: 'json', label: 'JSON',       icon: Database, desc: 'JSON Resume format (.json)' },
  { key: 'yaml', label: 'YAML',       icon: Database, desc: 'YAML resume (.yaml)' },
  { key: 'xml',  label: 'XML',        icon: Database, desc: 'XML resume (.xml)' },
] as const

type ExportFormatKey = (typeof EXPORT_FORMATS)[number]['key']

interface ExportDropdownProps {
  // One of these must be provided:
  resumeId?: string          // For saved resumes (workspace/edit pages)
  latexContent?: string      // For unsaved content (/try page)
  onPdfExport?: () => void   // If provided, called instead of apiClient for PDF
  className?: string
  /**
   * Visual variant:
   *  'toolbar' — compact, matches Import/Save buttons in the editor header
   *  'card'    — matches Edit/Optimize row buttons inside resume cards
   *  'inline'  — medium size, sits alongside px-4 py-2 toolbar buttons (/try page)
   */
  variant?: 'toolbar' | 'card' | 'inline'
}

/**
 * Download a blob as a file. Revokes the object URL after a short delay
 * to ensure the browser has time to start the download before cleanup.
 */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // Delay revocation to ensure the download has started
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function ExportDropdown({
  resumeId,
  latexContent,
  onPdfExport,
  className = '',
  variant = 'inline',
}: ExportDropdownProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState<ExportFormatKey | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [dropdownPos, setDropdownPos] = useState<{ top: number; right: number } | null>(null)
  const [mounted, setMounted] = useState(false)

  useEffect(() => { setMounted(true) }, [])

  const isExporting = loading !== null

  function openDropdown() {
    if (isExporting) return
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      setDropdownPos({
        top: rect.bottom + 6,
        right: window.innerWidth - rect.right,
      })
    }
    setIsOpen(true)
  }

  async function handleExport(format: ExportFormatKey) {
    // Prevent concurrent exports
    if (isExporting) return

    if (format === 'pdf') {
      setIsOpen(false)
      if (onPdfExport) {
        onPdfExport()
        return
      }
      toast.info('Use the compile button to generate PDF')
      return
    }

    // Validate content before hitting the API
    const hasContent = resumeId || (latexContent && latexContent.trim().length > 0)
    if (!hasContent) {
      toast.error('No resume content to export — write something first')
      setIsOpen(false)
      return
    }

    setLoading(format)
    setIsOpen(false)
    try {
      let blob: Blob
      if (resumeId) {
        blob = await apiClient.exportResume(resumeId, format)
      } else {
        blob = await apiClient.exportContent(latexContent!, format)
      }

      const formatInfo = EXPORT_FORMATS.find(f => f.key === format)
      downloadBlob(blob, `resume.${format}`)
      toast.success(`Downloaded as ${formatInfo?.label || format}`)
    } catch (err: unknown) {
      let message = err instanceof Error ? err.message : 'Export failed'
      if (message.includes('400')) message = 'Resume content is empty or invalid'
      else if (message.includes('403')) message = 'Access denied to this resume'
      else if (message.includes('404')) message = 'Resume not found'
      else if (message.includes('500') || message.includes('502') || message.includes('503'))
        message = 'Server error — please try again'
      toast.error(message)
    } finally {
      setLoading(null)
    }
  }

  // Trigger button classes per variant
  const triggerCls = (() => {
    const base = 'flex items-center gap-1.5 transition disabled:opacity-50'
    if (variant === 'toolbar') {
      return `${base} rounded-md px-2.5 py-1.5 text-[11px] font-medium text-zinc-500 hover:bg-white/[0.05] hover:text-zinc-200`
    }
    if (variant === 'card') {
      return `${base} w-full justify-center rounded-lg border border-white/10 bg-white/[0.05] px-3 py-2 text-xs font-semibold text-zinc-200 hover:bg-white/10`
    }
    return `${base} rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm text-zinc-200 hover:bg-white/10`
  })()

  const chevronSize = variant === 'toolbar' ? 10 : 12
  const iconSize    = variant === 'toolbar' ? 11 : 14

  return (
    <div className={`relative ${className}`}>
      <button
        ref={triggerRef}
        onClick={openDropdown}
        disabled={isExporting}
        className={triggerCls}
      >
        {isExporting ? (
          <Loader2 size={iconSize} className="animate-spin" />
        ) : (
          <Download size={iconSize} />
        )}
        Export
        <ChevronDown
          size={chevronSize}
          className={`transition-transform duration-150 ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Render dropdown via portal to escape overflow:hidden on parent cards/panels */}
      {mounted && isOpen && dropdownPos && createPortal(
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-[200]"
            onClick={() => setIsOpen(false)}
          />
          {/* Dropdown panel — fixed positioning so it's never clipped */}
          <div
            className="z-[201] w-56 overflow-hidden rounded-xl border border-white/10 bg-zinc-900 shadow-2xl shadow-black/60"
            style={{ position: 'fixed', top: dropdownPos.top, right: dropdownPos.right }}
          >
            <div className="px-3 pt-2.5 pb-1.5">
              <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-500 font-medium">
                Download As
              </p>
            </div>
            <div className="pb-1.5">
              {EXPORT_FORMATS.map((fmt) => {
                const Icon = fmt.icon
                const isLoading = loading === fmt.key
                return (
                  <button
                    key={fmt.key}
                    onClick={() => handleExport(fmt.key)}
                    disabled={isExporting}  // Disable ALL items while any export is in progress
                    className="w-full flex items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-white/[0.05] disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isLoading ? (
                      <Loader2 size={14} className="shrink-0 animate-spin text-orange-300" />
                    ) : (
                      <Icon size={14} className="shrink-0 text-zinc-500" />
                    )}
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-zinc-200">{fmt.label}</div>
                      <div className="text-[11px] text-zinc-600 truncate">{fmt.desc}</div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        </>,
        document.body
      )}
    </div>
  )
}
