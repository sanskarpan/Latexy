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

export const digest = (value: string | Buffer) => createHash('sha256').update(value).digest('hex')
export const normalizedText = (value: string) => value.replace(/\s+/g, ' ').trim()
const runFile = promisify(execFile)

export type Admission = {
  source: string; fingerprint: string; jobType: string; status: number; jobId: string
}
export type PreviewResponse = {
  jobId: string; artifactId: string; kind: 'pdf' | 'geometry' | 'synctex'
  status: number; fingerprint: string; body: Buffer; geometry?: ArtifactGeometry
}

/** Observers only: no routes, socket substitutes, auth or artifact fixtures. */
export function observeRealPreview(page: Page, apiOrigin: string) {
  const admissions: Admission[] = []
  const artifacts = new Map<string, RenderArtifact>()
  const previews: PreviewResponse[] = []
  const events: Array<{ type: string; jobId: string }> = []
  const runtimeErrors: string[] = []
  const captureErrors: string[] = []
  const pending = new Set<Promise<void>>()
  let externalRequests = 0
  page.on('request', request => { if (!isLocalPreviewResource(request.url())) externalRequests++ })
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
    const body = await response.body()
    if (body.length > 20 * 1024 * 1024) throw new Error('Artifact response exceeds the normal preview cap')
    previews.push({ jobId: match[1], artifactId: match[2], kind, status: response.status(), body,
      fingerprint: response.request().headers()['x-device-fingerprint'] ?? '',
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
    async settle() { await Promise.all([...pending]) },
    preview(jobId: string, artifactId: string, kind: PreviewResponse['kind']) {
      return previews.find(value => value.jobId === jobId && value.artifactId === artifactId && value.kind === kind && value.status === 200)
    },
    // An API read confirms durable completion without feeding fabricated state
    // into the frontend or depending on a transient progress-strip label.
    async completedState(jobId: string) {
      const response = await page.request.get(`${apiOrigin}/jobs/${encodeURIComponent(jobId)}/state`)
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
