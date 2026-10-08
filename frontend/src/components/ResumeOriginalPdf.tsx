'use client'

import { useEffect, useRef, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import type { PdfImportReceipt } from '@/lib/pdf-import-types'
import { sha256Bytes } from '@/hooks/useArtifactPreview'
import PDFPreview from '@/components/PDFPreview'

/** Original uploads are owner-only attachments, never editable/export artifacts. */
export default function ResumeOriginalPdf({ resumeId, ownerId }: { resumeId: string; ownerId: string }) {
  const [receiptSnapshot, setReceiptSnapshot] = useState<{ identity: string; receipt: PdfImportReceipt } | null>(null)
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const token = apiClient.getAuthToken()
  const identity = `${ownerId}:${resumeId}`
  // Effects run after paint. Hide another owner's attachment at render time,
  // including its open blob preview, before asynchronous cleanup runs.
  const receipt = receiptSnapshot?.identity === identity ? receiptSnapshot.receipt : null
  const currentIdentity = useRef(identity)
  currentIdentity.current = identity

  useEffect(() => {
    let stopped = false
    const controller = new AbortController()
    setReceiptSnapshot(null); setOpen(false)
    if (token) void apiClient.getResumePdfImport(resumeId, {
      authToken: token, isCurrent: () => !stopped && currentIdentity.current === identity,
    }, controller.signal).then((result) => {
      if (!stopped && currentIdentity.current === identity) setReceiptSnapshot({ identity, receipt: result })
    }).catch(() => { /* Most resumes have no original upload; collaborators cannot access it. */ })
    return () => { stopped = true; controller.abort() }
  }, [resumeId, identity, token])

  useEffect(() => {
    if (!open || !receipt || !token) return
    const controller = new AbortController()
    let stopped = false
    let objectUrl: string | null = null
    const isCurrent = () => !stopped && currentIdentity.current === identity
    setLoading(true); setError(null); setUrl(null)
    closeRef.current?.focus()
    void (async () => {
      try {
        const blob = await apiClient.downloadPdfImportOriginal(receipt.import_id, { authToken: token, isCurrent }, controller.signal)
        if (blob.size !== receipt.original.size_bytes || await sha256Bytes(await blob.arrayBuffer()) !== receipt.original.sha256) {
          throw new Error('The original PDF could not be verified.')
        }
        if (!isCurrent()) return
        objectUrl = URL.createObjectURL(blob); setUrl(objectUrl)
      } catch (cause) {
        if (isCurrent()) setError(cause instanceof Error ? cause.message : 'The original PDF could not be loaded.')
      } finally { if (isCurrent()) setLoading(false) }
    })()
    return () => {
      stopped = true; controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [open, receipt, token, identity])

  if (!receipt) return null
  function close() { setOpen(false); buttonRef.current?.focus() }
  return <>
    <button ref={buttonRef} type="button" onClick={() => setOpen(true)} className="text-[11px] text-accent-strong hover:underline">Original PDF</button>
    {open && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3" onKeyDown={(event) => {
      if (event.key === 'Escape') { event.stopPropagation(); close() }
      if (event.key === 'Tab') {
        const controls = event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }}>
      <section role="dialog" aria-modal="true" aria-labelledby="original-pdf-title" className="flex h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-line bg-surface">
        <div className="flex items-center justify-between gap-4 border-b border-line p-4">
          <div><h2 id="original-pdf-title" className="text-sm font-semibold text-fg">Original uploaded PDF</h2>
            <p className="text-xs text-fg-3">Read-only attachment. Your editable resume uses its selected layout.</p></div>
          <button ref={closeRef} type="button" onClick={close} className="text-xs text-fg-2">Close original PDF</button>
        </div>
        {error && <p role="alert" className="p-3 text-sm text-err">{error}</p>}
        <div className="min-h-0 flex-1"><PDFPreview pdfUrl={url} isLoading={loading} revisionLabel="Original upload · read-only" /></div>
      </section>
    </div>}
  </>
}
