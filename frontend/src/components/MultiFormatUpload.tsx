'use client'

import { useCallback, useRef, useState } from 'react'
import { Upload, File, FileText, Image as ImageIcon, Code, X, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useFormatConversion } from '@/hooks/useFormatConversion'

const ACCEPTED_FORMATS = [
  '.tex', '.latex', '.ltx',
  '.pdf',
  '.docx', '.doc',
  '.md', '.markdown', '.mdx',
  '.txt', '.text',
  '.html', '.htm',
  '.json',
  '.yaml', '.yml',
  '.toml',
  '.xml',
  '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp',
].join(',')

function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'].includes(ext))
    return <ImageIcon className="w-4 h-4 text-violet-300" />
  if (['tex', 'latex', 'ltx'].includes(ext))
    return <Code className="w-4 h-4 text-orange-300" />
  if (['pdf'].includes(ext))
    return <FileText className="w-4 h-4 text-rose-300" />
  if (['docx', 'doc'].includes(ext))
    return <FileText className="w-4 h-4 text-blue-300" />
  if (['md', 'markdown', 'mdx'].includes(ext))
    return <FileText className="w-4 h-4 text-emerald-300" />
  return <File className="w-4 h-4 text-zinc-400" />
}

function getFormatLabel(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    tex: 'LaTeX', latex: 'LaTeX', ltx: 'LaTeX',
    pdf: 'PDF', docx: 'Word', doc: 'Word (Legacy)',
    md: 'Markdown', markdown: 'Markdown', mdx: 'MDX',
    txt: 'Plain Text', text: 'Plain Text',
    html: 'HTML', htm: 'HTML',
    json: 'JSON', yaml: 'YAML', yml: 'YAML',
    toml: 'TOML', xml: 'XML',
    jpg: 'Image', jpeg: 'Image', png: 'Image', gif: 'Image',
    bmp: 'Image', tiff: 'Image', webp: 'Image',
  }
  return map[ext] || ext.toUpperCase()
}

interface MultiFormatUploadProps {
  onFileUpload: (content: string) => void
}

export default function MultiFormatUpload({ onFileUpload }: MultiFormatUploadProps) {
  const [isDragOver, setIsDragOver] = useState(false)
  const [uploadedFile, setUploadedFile] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const { status, progress, convertedLatex, error, startConversion, reset } = useFormatConversion()

  const isTexFile = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase() || ''
    return ['tex', 'latex', 'ltx'].includes(ext)
  }

  const handleFile = useCallback(async (file: File) => {
    setUploadedFile(file.name)

    // LaTeX files — read directly, no server call needed
    if (isTexFile(file.name)) {
      try {
        const content = await file.text()
        onFileUpload(content)
      } catch {
        toast.error('Error reading LaTeX file')
        setUploadedFile(null)
      }
      return
    }

    // Other formats — upload for conversion
    const result = await startConversion(file)
    if (result) {
      onFileUpload(result)
      toast.success(`${getFormatLabel(file.name)} file converted to LaTeX`)
    }
  }, [onFileUpload, startConversion])

  // Watch for async conversion completion
  const prevStatusRef = useRef(status)
  const prevStatus = prevStatusRef.current
  prevStatusRef.current = status
  if (status === 'done' && convertedLatex && prevStatus === 'converting') {
    onFileUpload(convertedLatex)
    toast.success('File converted to LaTeX successfully')
  }
  if (status === 'error' && error && prevStatus !== 'error') {
    toast.error(`Conversion failed: ${error}`)
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
    e.target.value = ''
  }, [handleFile])

  const clearFile = useCallback(() => {
    setUploadedFile(null)
    reset()
    onFileUpload('')
  }, [reset, onFileUpload])

  // Uploaded + done state
  if (uploadedFile && (status === 'idle' || status === 'done')) {
    return (
      <div className="w-full rounded-xl border border-emerald-400/20 bg-emerald-500/5 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <CheckCircle className="w-4 h-4 shrink-0 text-emerald-300" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-zinc-200 flex items-center gap-1.5 truncate">
                {getFileIcon(uploadedFile)}
                <span className="truncate">{uploadedFile}</span>
              </p>
              <p className="text-xs text-zinc-500 mt-0.5">
                {isTexFile(uploadedFile) ? 'LaTeX file loaded' : `${getFormatLabel(uploadedFile)} converted to LaTeX`}
              </p>
            </div>
          </div>
          <button
            onClick={clearFile}
            className="shrink-0 rounded-md p-1.5 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>
      </div>
    )
  }

  // Converting state
  if (status === 'uploading' || status === 'converting') {
    return (
      <div className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 py-4">
        <div className="flex items-center gap-3 mb-3">
          <Loader2 className="w-4 h-4 shrink-0 text-orange-300 animate-spin" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-zinc-200 truncate">{uploadedFile}</p>
            <p className="text-xs text-zinc-500 mt-0.5">
              {status === 'uploading' ? 'Uploading…' : `Converting to LaTeX… ${progress}%`}
            </p>
          </div>
        </div>
        {status === 'converting' && (
          <div className="w-full rounded-full bg-white/[0.06] h-1">
            <div
              className="bg-orange-300 h-1 rounded-full transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}
      </div>
    )
  }

  // Error state
  if (status === 'error') {
    return (
      <div className="w-full rounded-xl border border-rose-400/20 bg-rose-500/5 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-300" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-zinc-200">Conversion failed</p>
              <p className="text-xs text-rose-300 mt-0.5 truncate">{error}</p>
            </div>
          </div>
          <button
            onClick={clearFile}
            className="shrink-0 rounded-md p-1.5 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>
      </div>
    )
  }

  // Default idle upload UI
  return (
    <div className="w-full">
      <div
        className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          isDragOver
            ? 'border-orange-300/50 bg-orange-300/[0.04]'
            : 'border-white/10 hover:border-white/20'
        }`}
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
        onDragLeave={() => setIsDragOver(false)}
      >
        <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/[0.04]">
          <Upload className="w-5 h-5 text-zinc-400" />
        </div>

        <h3 className="text-sm font-semibold text-zinc-100 mb-1">
          Upload Resume
        </h3>

        <p className="text-xs text-zinc-500 mb-5">
          Drop any resume file here, or click to browse
        </p>

        <label className="btn-primary cursor-pointer inline-flex items-center gap-2 px-4 py-2 text-sm">
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_FORMATS}
            onChange={handleFileSelect}
            className="hidden"
          />
          <File size={14} />
          Choose File
        </label>

        <p className="text-[11px] text-zinc-600 mt-4 leading-relaxed">
          PDF · Word · Markdown · LaTeX · JSON · YAML · HTML · images · and more
        </p>
      </div>
    </div>
  )
}
