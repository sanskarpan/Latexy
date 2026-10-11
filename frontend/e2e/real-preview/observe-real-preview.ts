import type { Page, Request, Response } from '@playwright/test'
import { createHash } from 'node:crypto'
import { execFile } from 'node:child_process'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import type { RenderArtifact } from '../../src/lib/event-types'
import type { ArtifactGeometry } from '../../src/lib/resume-engine-types'
import { isLocalPreviewResource } from '../../scripts/real-preview-contract.mjs'
import { installBrowserPdfCapture, type BrowserPdfCapture, type PdfCaptureController } from './capture-browser-pdf'

export const digest = (value: string | Buffer) => createHash('sha256').update(value).digest('hex')
export const normalizedText = (value: string) => value.replace(/\s+/g, ' ').trim()
const runFile = promisify(execFile)

/** Wrapped fields have several exact-label line boxes for the same node. */
export function semanticFieldHitTarget(page: Page, text: string) {
  return page.getByRole('button', { name: `Edit resume field: ${text}`, exact: true }).first()
}

export type Admission = {
  source: string; fingerprint: string; jobType: string; status: number; jobId: string
}
export type PreviewResponse = {
  jobId: string; artifactId: string; kind: 'pdf' | 'geometry' | 'synctex'
  status: number; fingerprint: string; requestId: string; body: Buffer; geometry?: ArtifactGeometry
}

type ArtifactTransfer = {
  jobId: string; artifactId: string; kind: PreviewResponse['kind']; fingerprint: string; requestId: string
  method: string; status: number; resourceType: string; fromServiceWorker: boolean
  contentType: string; contentLength: number | null; contentEncoding: string; bodyBytes: number | null
}
const PDF_BINDING = '__latexyObserveRealPreviewPdf'
const MAX_PDF_BYTES = 20 * 1024 * 1024
const MAX_TRANSFERS = 24

/** Observers only: no routes, socket substitutes, auth or artifact fixtures.
 * PDF bytes come from a clone of the original browser fetch Response, never a
 * second request. See upstream Playwright #42862 for the matching CDP-body bug.
 */
export async function observeRealPreview(page: Page, apiOrigin: string) {
  const admissions: Admission[] = []
  const artifacts = new Map<string, RenderArtifact>()
  const previews: PreviewResponse[] = []
  const events: Array<{ type: string; jobId: string }> = []
  const runtimeErrors: string[] = []
  const captureErrors: string[] = []
  const transfers: ArtifactTransfer[] = []
  const failedTransfers: Array<{ kind: PreviewResponse['kind']; method: string }> = []
  const pending = new Set<Promise<void>>()
  let externalRequests = 0
  let disposed = false
  let pdfDeliveries = 0
  const bindingHandle = await page.exposeFunction(PDF_BINDING, (value: BrowserPdfCapture) => {
    if (disposed) return
    if (++pdfDeliveries > 7) {
      if (pdfDeliveries === 8) captureErrors.push('pdf_capture_count_limit')
      return
    }
    if (value.error) {
      captureErrors.push(['pdf_capture_http_status', 'pdf_capture_content_type', 'pdf_capture_byte_limit',
        'pdf_capture_deadline', 'pdf_capture_count_limit', 'pdf_capture_read_failure'].includes(value.error)
        ? value.error : 'pdf_capture_failure')
      return
    }
    if (!Number.isFinite(value.deadlineAt) || Date.now() > value.deadlineAt) {
      captureErrors.push('pdf_capture_deadline'); return
    }
    if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.jobId)
      || !/^[a-f0-9]{64}$/.test(value.artifactId) || typeof value.fingerprint !== 'string'
      || !value.fingerprint || value.fingerprint.length > 512 || typeof value.requestId !== 'string'
      || !value.requestId || value.requestId.length > 128
      || value.status !== 200 || !Number.isInteger(value.bodyBytes) || value.bodyBytes! < 0 || value.bodyBytes! > MAX_PDF_BYTES
      || typeof value.bodyBase64 !== 'string' || value.bodyBase64.length > Math.ceil(MAX_PDF_BYTES / 3) * 4
      || !/^[A-Za-z0-9+/]*={0,2}$/.test(value.bodyBase64)) {
      captureErrors.push('pdf_capture_payload_invalid'); return
    }
    const body = Buffer.from(value.bodyBase64, 'base64')
    if (body.length !== value.bodyBytes || body.length < 5 || body.subarray(0, 5).toString() !== '%PDF-') {
      captureErrors.push('pdf_capture_bytes_invalid')
    }
    previews.push({ jobId: value.jobId, artifactId: value.artifactId, kind: 'pdf', status: value.status,
      fingerprint: value.fingerprint, requestId: value.requestId, body })
  })
  const initHandle = await page.addInitScript(installBrowserPdfCapture, { apiOrigin, bindingName: PDF_BINDING,
    maxBytes: MAX_PDF_BYTES, maxCaptures: 6, deadlineMs: 10_000 })
  page.on('request', request => { if (!isLocalPreviewResource(request.url())) externalRequests++ })
  page.on('requestfailed', request => {
    const url = new URL(request.url())
    const match = /^\/download\/[^/]+\/preview\/[a-f0-9]{64}(?:\/(geometry|synctex))?$/.exec(url.pathname)
    if (url.origin === apiOrigin && match && failedTransfers.length < MAX_TRANSFERS) {
      failedTransfers.push({ kind: (match[1] ?? 'pdf') as PreviewResponse['kind'], method: request.method() })
    }
  })
  // Error names contain no source, token, identity or third-party URL.
  page.on('pageerror', error => runtimeErrors.push(error.name))
  page.on('websocket', socket => {
    if (!isLocalPreviewResource(socket.url())) externalRequests++
    socket.on('framereceived', frame => {
      try {
        const event = JSON.parse(String(frame.payload)).event
        if (event?.job_id && ['artifact.ready', 'job.completed', 'job.failed', 'job.cancelled'].includes(event.type)) {
          events.push({ type: event.type, jobId: event.job_id })
          if (event.type === 'artifact.ready') artifacts.set(event.job_id, event)
        }
      } catch { /* The transport also carries non-event control frames. */ }
    })
  })

  async function capture(response: Response) {
    const url = new URL(response.url())
    if (url.origin !== apiOrigin) return
    if (url.pathname === '/jobs/submit' && response.request().method() === 'POST') {
      const submitted = response.request().postDataJSON()
      const body = await response.json()
      admissions.push({ source: submitted.latex_content, fingerprint: submitted.device_fingerprint,
        jobType: submitted.job_type, status: response.status(), jobId: body.job_id })
    }
    const match = /^\/download\/([^/]+)\/preview\/([a-f0-9]{64})(?:\/(geometry|synctex))?$/.exec(url.pathname)
    if (!match) return
    const kind = (match[3] ?? 'pdf') as PreviewResponse['kind']
    if (transfers.length >= MAX_TRANSFERS) throw new Error('Artifact transfer count exceeds the observation bound')
    const headers = response.headers()
    const length = Number(headers['content-length'])
    const media = headers['content-type']?.split(';', 1)[0].trim().toLowerCase() ?? ''
    const encoding = headers['content-encoding']?.trim().toLowerCase() ?? ''
    const transfer: ArtifactTransfer = { jobId: match[1], artifactId: match[2], kind,
      fingerprint: response.request().headers()['x-device-fingerprint'] ?? '',
      requestId: response.request().headers()['x-request-id'] ?? '', method: response.request().method(),
      status: response.status(), resourceType: response.request().resourceType(), fromServiceWorker: response.fromServiceWorker(),
      contentType: ['application/pdf', 'application/json', 'text/plain'].includes(media) ? media : 'other',
      contentLength: headers['content-length'] && Number.isSafeInteger(length) && length >= 0 ? length : null,
      contentEncoding: ['', 'identity', 'gzip', 'br', 'deflate'].includes(encoding) ? encoding || 'none' : 'other', bodyBytes: null }
    transfers.push(transfer)
    // OPTIONS/HEAD are not artifact bodies. PDF body() is deliberately never
    // read through CDP: the clone observer captures the same original GET.
    if (transfer.method !== 'GET' || kind === 'pdf') return
    const body = await response.body()
    transfer.bodyBytes = body.length
    if (body.length > 20 * 1024 * 1024) throw new Error('Artifact response exceeds the normal preview cap')
    previews.push({ jobId: match[1], artifactId: match[2], kind, status: response.status(), body,
      fingerprint: transfer.fingerprint, requestId: transfer.requestId,
      geometry: kind === 'geometry' && response.ok() ? JSON.parse(body.toString('utf8')) : undefined })
  }
  page.on('response', response => {
    const operation = capture(response).catch(() => {
      // Only report the resource kind, never a response body or exception text.
      captureErrors.push(new URL(response.url()).pathname.includes('/preview/') ? 'artifact_capture' : 'admission_capture')
    }).finally(() => pending.delete(operation))
    pending.add(operation)
  })

  return {
    admissions, artifacts, previews, events, runtimeErrors, captureErrors,
    externalRequestCount: () => externalRequests,
    async settle() {
      await Promise.all([...pending])
      const errors = await page.evaluate(async () => {
        const controller = (window as typeof window & { __latexyRealPreviewCapture?: PdfCaptureController }).__latexyRealPreviewCapture
        return controller ? await controller.settle() : []
      })
      for (const error of errors) if (!captureErrors.includes(error)) captureErrors.push(error)
    },
    async dispose() {
      try { await this.settle() } catch { captureErrors.push('pdf_capture_settle_failure') }
      disposed = true
      try {
        await page.evaluate(() => (window as typeof window & { __latexyRealPreviewCapture?: PdfCaptureController }).__latexyRealPreviewCapture?.cleanup())
      } catch { captureErrors.push('pdf_capture_cleanup_failure') }
      // Use the owned Disposable handles supported by locked Playwright 1.64.
      for (const handle of [initHandle, bindingHandle]) {
        try { await handle.dispose() } catch { captureErrors.push('pdf_capture_cleanup_failure') }
      }
    },
    transferDiagnostics() {
      return { responses: transfers.map(transfer => {
        const body = previews.find(value => value.kind === transfer.kind && value.jobId === transfer.jobId
          && value.artifactId === transfer.artifactId && value.requestId === transfer.requestId && value.fingerprint === transfer.fingerprint)
        const admission = admissions.find(value => value.jobId === transfer.jobId)
        return { job_sha256: digest(transfer.jobId), artifact_id: transfer.artifactId, kind: transfer.kind,
          method: transfer.method, status: transfer.status, resource_type: transfer.resourceType,
          from_service_worker: transfer.fromServiceWorker, content_type: transfer.contentType,
          content_length: transfer.contentLength, content_encoding: transfer.contentEncoding,
          body_bytes: body?.body.length ?? transfer.bodyBytes, body_sha256: body ? digest(body.body) : null,
          fingerprint_matches_admission: Boolean(admission && admission.fingerprint === transfer.fingerprint),
          capture_channel: transfer.kind === 'pdf' ? 'original-browser-response-clone' : 'playwright-response-body' }
      }), failed_requests: failedTransfers }
    },
    preview(jobId: string, artifactId: string, kind: PreviewResponse['kind']) {
      if (captureErrors.length) throw new Error('The original browser artifact capture failed')
      return previews.find(value => value.jobId === jobId && value.artifactId === artifactId && value.kind === kind && value.status === 200
        && transfers.some(transfer => transfer.jobId === jobId && transfer.artifactId === artifactId
          && transfer.kind === kind && transfer.method === 'GET' && transfer.status === 200
          && transfer.requestId === value.requestId && transfer.fingerprint === value.fingerprint))
    },
    // An API read confirms durable completion without feeding fabricated state
    // into the frontend or depending on a transient progress-strip label.
    async completedState(jobId: string) {
      const admission = admissions.find(value => value.jobId === jobId)
      if (!admission?.fingerprint) throw new Error('Job state requires its observed guest admission identity')
      const response = await page.request.get(`${apiOrigin}/jobs/${encodeURIComponent(jobId)}/state`, {
        headers: { 'X-Device-Fingerprint': admission.fingerprint }, timeout: 15_000,
      })
      if (!response.ok()) throw new Error('The real job state could not be read')
      const body = await response.json()
      return body.status as string
    },
  }
}

/** Extract text from the exact received bytes; delete the private temp PDF. */
export async function extractReceivedPdfText(pdf: Buffer): Promise<string> {
  if (pdf.length < 5 || pdf.length > 20 * 1024 * 1024 || pdf.subarray(0, 5).toString() !== '%PDF-') {
    throw new Error('The received artifact is not a bounded PDF')
  }
  const folder = await mkdtemp(join(tmpdir(), 'latexy-real-preview-'))
  try {
    const filename = join(folder, 'received.pdf')
    await writeFile(filename, pdf, { mode: 0o600 })
    const { stdout } = await runFile('pdftotext', ['-layout', filename, '-'], { timeout: 10_000, maxBuffer: 1024 * 1024 })
    return normalizedText(stdout)
  } finally {
    await rm(folder, { recursive: true, force: true })
  }
}

export function isAdmissionRequest(request: Request, apiOrigin: string) {
  const url = new URL(request.url())
  return url.origin === apiOrigin && url.pathname === '/jobs/submit' && request.method() === 'POST'
}
