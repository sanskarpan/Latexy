'use client'

import { useEffect, useRef, useState } from 'react'
import { apiClient, type AccountPreferenceRequestContext } from '@/lib/api-client'
import type { PdfImportReceipt } from '@/lib/pdf-import-types'
import { sha256Bytes } from '@/hooks/useArtifactPreview'
import PDFPreview from '@/components/PDFPreview'

export default function PdfImportWizard({ file, title, ownerId, onCreated, onCancel }: {
  file: File; title: string; ownerId: string
  onCreated: (resumeId: string) => void; onCancel: () => void
}) {
  const [receipt, setReceipt] = useState<PdfImportReceipt | null>(null)
  const [originalUrl, setOriginalUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [templateId, setTemplateId] = useState('')
  const [edits, setEdits] = useState<Record<string, string>>({})
  const identity = useRef({ ownerId, file, generation: 0 })
  if (identity.current.ownerId !== ownerId || identity.current.file !== file) {
    identity.current = { ownerId, file, generation: identity.current.generation + 1 }
  }
  const mounted = useRef(false)
  const savingRef = useRef(false)
  const receiptIdentity = useRef<{ ownerId: string; file: File; generation: number } | null>(null)
  const receiptMatches = receiptIdentity.current?.ownerId === ownerId && receiptIdentity.current.file === file
    && receiptIdentity.current.generation === identity.current.generation
  const hasReviewedContent = receiptMatches && (receipt?.extraction.fields.some((field) => (edits[field.field_id] ?? field.text).trim()) ?? false)

  useEffect(() => {
    mounted.current = true
    const generation = identity.current.generation
    const controller = new AbortController()
    let url: string | null = null
    const isCurrent = () => mounted.current && identity.current.ownerId === ownerId
      && identity.current.file === file && identity.current.generation === generation && !controller.signal.aborted
    const token = apiClient.getAuthToken()
    setReceipt(null); setOriginalUrl(null); setEdits({}); setTemplateId(''); setError(null); setLoading(true)
    const context: AccountPreferenceRequestContext | null = token ? { authToken: token, isCurrent } : null
    void (async () => {
      try {
        if (!context) throw new Error('Your session is not ready. Sign in again to import this PDF.')
        if (!file.size || file.size > 10 * 1024 * 1024) throw new Error('Choose a PDF no larger than 10 MB.')
        const selectedHash = await sha256Bytes(await file.arrayBuffer())
        if (!isCurrent()) return
        const uploaded = await apiClient.uploadPdfImport(file, context, controller.signal)
        if (!isCurrent()) return
        if (uploaded.original.size_bytes !== file.size || uploaded.original.sha256 !== selectedHash) {
          throw new Error('The preserved PDF does not match the file you selected. Choose the file again.')
        }
        receiptIdentity.current = { ownerId, file, generation }
        setReceipt(uploaded)
        const blob = await apiClient.downloadPdfImportOriginal(uploaded.import_id, context, controller.signal)
        if (blob.size !== uploaded.original.size_bytes
          || await sha256Bytes(await blob.arrayBuffer()) !== uploaded.original.sha256) {
          throw new Error('The original PDF could not be verified. Choose the file again.')
        }
        if (!isCurrent()) return
        url = URL.createObjectURL(blob)
        setOriginalUrl(url)
      } catch (cause) {
        if (isCurrent()) setError(cause instanceof Error ? cause.message : 'This PDF could not be imported.')
      } finally { if (isCurrent()) setLoading(false) }
    })()
    return () => {
      mounted.current = false
      controller.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [file, ownerId])

  async function createEditableResume() {
    if (!receipt || !receiptMatches || !originalUrl || savingRef.current || !templateId || !title.trim() || !hasReviewedContent) return
    const generation = identity.current.generation
    const isCurrent = () => mounted.current && identity.current.ownerId === ownerId
      && identity.current.file === file && identity.current.generation === generation
    const token = apiClient.getAuthToken()
    if (!token || !isCurrent()) return
    savingRef.current = true; setSaving(true); setError(null)
    try {
      const result = await apiClient.adaptPdfImport(receipt.import_id, {
        title: title.trim(), template_id: templateId, expected_original_sha256: receipt.original.sha256,
        field_edits: receipt.extraction.fields.filter((field) => edits[field.field_id] !== undefined && edits[field.field_id] !== field.text)
          .map((field) => ({ node_id: field.field_id, expected_node_revision: field.node_revision, text: edits[field.field_id] })),
      }, { authToken: token, isCurrent })
      if (isCurrent()) onCreated(result.resume_id)
    } catch (cause) {
      if (isCurrent()) setError(cause instanceof Error ? cause.message : 'Your editable resume could not be created.')
    } finally {
      savingRef.current = false
      if (isCurrent()) setSaving(false)
    }
  }

  return <section aria-label="Review PDF import" className="space-y-5">
    <div className="flex items-start justify-between gap-4">
      <div><h2 className="text-base font-semibold text-fg">Keep your original. Choose your editable layout.</h2>
        <p className="mt-1 text-sm text-fg-2">Your uploaded PDF stays unchanged. Review the extracted text, then choose a supported layout to create an editable resume.</p></div>
      <button type="button" disabled={saving} onClick={onCancel} className="shrink-0 text-xs text-fg-2 disabled:opacity-50">Choose another file</button>
    </div>
    {error && <p role="alert" className="rounded-lg bg-err/10 p-3 text-sm text-err">{error}</p>}
    {loading && <p role="status" className="text-sm text-fg-2">Preserving your PDF and extracting its text…</p>}
    {receipt && receiptMatches && <div className="grid gap-5 lg:grid-cols-2">
      <div className="min-h-[420px] overflow-hidden rounded-lg border border-line">
        <PDFPreview pdfUrl={originalUrl} isLoading={loading} revisionLabel="Original upload · read-only" />
      </div>
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-fg">Review extracted fields</h3>
        <p className="text-xs text-fg-3">PDFs do not preserve every editable field. Check the text below; extraction confidence is unknown unless the parser can verify it.</p>
        {receipt.extraction.warnings.map((warning, index) => <p key={index} className="text-xs text-warn">{warning}</p>)}
        {receipt.extraction.status === 'unavailable' && <p role="status" className="text-sm text-fg-2">We could not extract editable fields safely. Your original PDF is preserved. Add your details below before choosing an editable layout, or choose another file.</p>}
        <div className="max-h-[480px] space-y-3 overflow-auto">
          {receipt.extraction.fields.slice(0, 100).map((field, index) => <div key={field.field_id}>
            <label htmlFor={`pdf-import-field-${index}`} className="block text-xs font-medium text-fg">{field.label}</label>
            <p className="mt-1 text-[11px] text-fg-3">Extraction confidence: {field.confidence}</p>
            <textarea id={`pdf-import-field-${index}`} rows={2} maxLength={4000} disabled={saving}
              value={edits[field.field_id] ?? field.text} onChange={(event) => setEdits((previous) => ({ ...previous, [field.field_id]: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg" />
            {field.warnings.map((warning, warningIndex) => <p key={warningIndex} className="text-xs text-warn">{warning}</p>)}
          </div>)}
        </div>
        <label className="block text-xs font-medium text-fg" htmlFor="pdf-import-template">Editable layout</label>
        <select id="pdf-import-template" value={templateId} disabled={saving || loading} onChange={(event) => setTemplateId(event.target.value)}
          className="w-full rounded-lg border border-line bg-surface p-3 text-sm text-fg">
          <option value="">Choose a layout</option>
          {receipt.supported_templates.map((template) => <option key={template.template_id} value={template.template_id}>{template.name}</option>)}
        </select>
        <p className="text-xs text-fg-3">The editable version will use this layout. Your original PDF remains available separately.</p>
        {!title.trim() && <p className="text-xs text-fg-2">Enter a resume title above before creating the editable version.</p>}
        <button type="button" onClick={createEditableResume}
          disabled={saving || loading || !originalUrl || !templateId || !title.trim() || !hasReviewedContent}
          className="rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">
          {saving ? 'Creating editable resume…' : 'Create editable resume'}
        </button>
      </div>
    </div>}
  </section>
}
