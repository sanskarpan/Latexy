'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Download, ChevronDown, Loader2, FileText, Code, File, Globe, Database, Palette, Image, Mail, Cloud } from 'lucide-react'
import { Figma } from '@/components/icons/brand-icons'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import { downloadBlob } from '@/lib/download'

const EXPORT_FORMATS = [
  { key: 'pdf',   label: 'PDF',        icon: FileText, desc: 'Compiled PDF document' },
  { key: 'email', label: 'Email me',  icon: Mail,     desc: 'Send the compiled PDF to your verified account email' },
  { key: 'svg',   label: 'SVG',        icon: Image,    desc: 'First page as a genuine SVG image' },
  { key: 'jpeg',  label: 'JPEG',       icon: Image,    desc: 'First page as a JPEG image' },
  { key: 'tex',   label: 'LaTeX',      icon: Code,     desc: 'LaTeX source code (.tex)' },
  { key: 'docx',  label: 'Word',       icon: FileText, desc: 'Microsoft Word (.docx)' },
  { key: 'md',    label: 'Markdown',   icon: File,     desc: 'Markdown (.md)' },
  { key: 'html',  label: 'HTML',       icon: Globe,    desc: 'Web page (.html)' },
  { key: 'txt',   label: 'Plain Text', icon: File,     desc: 'Unformatted plain text (.txt)' },
  { key: 'json',  label: 'JSON',       icon: Database, desc: 'JSON Resume format (.json)' },
  { key: 'yaml',  label: 'YAML',       icon: Database, desc: 'YAML resume (.yaml)' },
  { key: 'xml',   label: 'XML',        icon: Database, desc: 'XML resume (.xml)' },
  { key: 'epub',  label: 'ePub',       icon: File,     desc: 'ePub document (.epub)' },
  { key: 'odf',   label: 'ODF',        icon: File,     desc: 'OpenDocument text (.odt)' },
  { key: 'docbook', label: 'DocBook',  icon: Code,     desc: 'DocBook 5 XML (.docbook)' },
  { key: 'canva', label: 'Canva',      icon: Palette,  desc: 'Opens resume in Canva with pre-filled content' },
  { key: 'figma', label: 'Figma JSON', icon: Figma,    desc: 'Download JSON for the Latexy Figma plugin' },
  { key: 'google_drive', label: 'Google Drive', icon: Cloud, desc: 'Export the latest compiled PDF to your Google Drive' },
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

export default function ExportDropdown({
  resumeId,
  latexContent,
  onPdfExport,
  className = '',
  variant = 'inline',
}: ExportDropdownProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState<ExportFormatKey | null>(null)
  const [exportError, setExportError] = useState<{ format: ExportFormatKey; message: string } | null>(null)
  const [driveNeedsConnection, setDriveNeedsConnection] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [dropdownPos, setDropdownPos] = useState<{
    top?: number
    bottom?: number
    right: number
    maxHeight: number
  } | null>(null)
  const [mounted, setMounted] = useState(false)

  useEffect(() => { setMounted(true) }, [])

  const isExporting = loading !== null

  function openDropdown() {
    if (isExporting) return
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const margin = 12
      const right = Math.max(margin, window.innerWidth - rect.right)
      const spaceBelow = window.innerHeight - rect.bottom - margin
      const spaceAbove = rect.top - margin
      // Open upward when there isn't enough room below and there's more room above.
      // Always cap max-height to the available space + scroll, so the menu can never
      // be clipped off-screen regardless of where the trigger sits.
      if (spaceBelow < 320 && spaceAbove > spaceBelow) {
        setDropdownPos({
          bottom: window.innerHeight - rect.top + 6,
          right,
          maxHeight: spaceAbove,
        })
      } else {
        setDropdownPos({
          top: rect.bottom + 6,
          right,
          maxHeight: spaceBelow,
        })
      }
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

    // Design/image exports only work for saved resumes (need resume_id and,
    // for images, the latest compiled PDF).
    if ((format === 'canva' || format === 'figma' || format === 'svg' || format === 'jpeg' || format === 'google_drive') && !resumeId) {
      toast.error(format === 'svg' || format === 'jpeg'
        ? 'Save and compile your resume first to export an image'
        : format === 'google_drive'
          ? 'Save your resume first to export to Google Drive'
          : 'Save your resume first to export to Canva or Figma')
      setIsOpen(false)
      return
    }

    if (format === 'email' && !resumeId) {
      toast.error('Save your resume first to email the compiled PDF')
      setIsOpen(false)
      return
    }

    // Validate content before hitting the API
    const hasContent = latexContent !== undefined
      ? latexContent.trim().length > 0
      : Boolean(resumeId)
    if (!hasContent) {
      toast.error('No resume content to export — write something first')
      setIsOpen(false)
      return
    }

    setLoading(format)
    setExportError(null)
    setDriveNeedsConnection(false)
    setIsOpen(false)
    try {
      if (format === 'canva' && resumeId) {
        const data = await apiClient.exportCanva(resumeId)
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        downloadBlob(blob, 'resume-canva.json')
        toast.success("Canva JSON downloaded — import it via Canva's Content Import feature", {
          duration: 6000,
        })
        return
      }

      if (format === 'figma' && resumeId) {
        const data = await apiClient.exportFigma(resumeId)
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        downloadBlob(blob, 'resume-figma.json')
        toast.success('Figma JSON downloaded — open it with the Latexy Figma plugin', {
          duration: 6000,
        })
        return
      }

      if (format === 'email' && resumeId) {
        const delivery = await apiClient.emailResumePdf(resumeId)
        const retryNote = delivery.retry_behavior === 'smtp_best_effort'
          ? ' Retrying through SMTP may create a duplicate.'
          : ''
        toast.success(`PDF email accepted for your verified account email.${retryNote}`, {
          duration: 7000,
        })
        return
      }

      if (format === 'google_drive' && resumeId) {
        const status = await apiClient.getGoogleDriveStatus()
        if (!status.connected) {
          setDriveNeedsConnection(true)
          setExportError({ format, message: 'Connect Google Drive in Settings before exporting.' })
          return
        }
        const result = await apiClient.exportResumeToGoogleDrive(resumeId)
        toast.success(result.action === 'created'
          ? 'Created the latest compiled PDF in Google Drive.'
          : 'Updated the existing Google Drive PDF for this resume. Retrying updates the same file.', {
            duration: 7000,
          })
        return
      }

      let blob: Blob
      // Prefer the live editor buffer when supplied. Exporting by resume ID
      // reads the last-saved database copy and silently drops unsaved edits.
      if ((format === 'svg' || format === 'jpeg') && resumeId) {
        // Raster/vector formats are rendered from the latest owned compiled
        // PDF. Never send the live LaTeX buffer to /export/content for these
        // formats, even when an editor supplies both props.
        blob = await apiClient.exportResume(resumeId, format)
      } else if (latexContent !== undefined) {
        blob = await apiClient.exportContent(latexContent, format)
      } else if (resumeId) {
        blob = await apiClient.exportResume(resumeId, format)
      } else {
        throw new Error('No resume content to export')
      }

      const formatInfo = EXPORT_FORMATS.find(f => f.key === format)
      downloadBlob(blob, `resume.${format}`)
      toast.success(`Downloaded as ${formatInfo?.label || format}`)
    } catch (err: unknown) {
      let message = err instanceof Error ? err.message : 'Export failed'
      if (message.includes('400')) message = 'Resume content is empty or invalid'
      else if (message.includes('403')) message = 'Access denied to this resume'
      else if (message.includes('404')) message = 'Resume not found'
      else if (format === 'email' && message.includes('503')) message = 'Email provider did not accept the PDF — please retry'
      else if (message.includes('500') || message.includes('502') || message.includes('503'))
        message = 'Server error — please try again'
      setExportError({ format, message })
      toast.error(message)
    } finally {
      setLoading(null)
    }
  }

  // Trigger button classes per variant
  const triggerCls = (() => {
    const base = 'flex items-center gap-1.5 transition disabled:opacity-50'
    if (variant === 'toolbar') {
      return `${base} rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium text-fg-3 hover:bg-surface-2 hover:text-fg`
    }
    if (variant === 'card') {
      return `${base} w-full justify-center rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs font-semibold text-fg hover:bg-surface-2`
    }
    return `${base} rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-4 py-2 text-sm text-fg hover:bg-surface-2`
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

      {exportError && (
        <div role="alert" className="mt-2 flex max-w-xs items-start gap-2 rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-2.5 py-2 text-xs text-err">
          <span className="min-w-0 flex-1">
            {exportError.message}
            {driveNeedsConnection && exportError.format === 'google_drive' && (
              <> <a href="/settings" className="font-semibold underline">Open Settings</a></>
            )}
          </span>
          <button type="button" onClick={() => void handleExport(exportError.format)} disabled={isExporting} className="shrink-0 font-semibold underline disabled:opacity-50">Retry</button>
        </div>
      )}

      {/* Render dropdown via portal to escape overflow:hidden on parent cards/panels */}
      {mounted && isOpen && dropdownPos && createPortal(
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-[200]"
            onClick={() => setIsOpen(false)}
          />
          {/* Dropdown panel — fixed positioning + capped height so it's never clipped */}
          <div
            className="z-[201] w-56 overflow-y-auto overscroll-contain rounded-[var(--radius-lg)] border border-line bg-surface shadow-[var(--shadow-2)]"
            style={{
              position: 'fixed',
              top: dropdownPos.top,
              bottom: dropdownPos.bottom,
              right: dropdownPos.right,
              maxHeight: dropdownPos.maxHeight,
            }}
          >
            <div className="px-3 pt-2.5 pb-1.5">
                <p className="text-[10px] uppercase tracking-[0.16em] text-fg-3 font-medium">
                Export or send
              </p>
            </div>
            <div className="pb-1.5">
              {EXPORT_FORMATS.map((fmt, idx) => {
                const Icon = fmt.icon
                const isLoading = loading === fmt.key
                const isDesignExport = fmt.key === 'canva' || fmt.key === 'figma'
                // Separator before design exports
                const showSeparator = idx > 0 && isDesignExport && !(['canva', 'figma'] as string[]).includes(EXPORT_FORMATS[idx - 1].key)
                return (
                  <div key={fmt.key}>
                    {showSeparator && (
                      <div className="mx-3 my-1 border-t border-line">
                        <p className="mt-1.5 mb-0.5 text-[10px] uppercase tracking-[0.14em] text-fg-3 font-medium">
                          Design Exports
                        </p>
                      </div>
                    )}
                    <button
                      onClick={() => handleExport(fmt.key)}
                      disabled={isExporting || ((fmt.key === 'canva' || fmt.key === 'figma' || fmt.key === 'svg' || fmt.key === 'jpeg' || fmt.key === 'google_drive') && !resumeId)}
                      title={fmt.desc}
                      className="w-full flex items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-surface-2 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isLoading ? (
                        <Loader2 size={14} className="shrink-0 animate-spin text-accent-strong" />
                      ) : (
                        <Icon size={14} className={`shrink-0 ${isDesignExport ? 'text-accent-strong' : 'text-fg-3'}`} />
                      )}
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-fg">{fmt.label}</div>
                        <div className="text-[11px] text-fg-3 truncate">{fmt.desc}</div>
                      </div>
                    </button>
                  </div>
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
