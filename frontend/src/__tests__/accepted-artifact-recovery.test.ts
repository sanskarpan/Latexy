import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ACCEPTED_ARTIFACT_RECOVERY_TIMEOUT_MS,
  fetchAcceptedArtifact,
  isCurrentAcceptedPreviewRecovery,
  isMatchingAcceptedArtifact,
  retryAfterMilliseconds,
  resolveCurrentAcceptedPreviewRecovery,
  shouldSubmitInitialPreview,
  type AcceptedPreviewRecoveryIdentity,
  type AcceptedPreviewRecoveryResponse,
} from '@/lib/accepted-artifact-recovery'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

const identity: AcceptedPreviewRecoveryIdentity = {
  ownerId: 'owner-a', resumeId: 'resume-a', generation: 3, source: 'current source', contentRevision: 9,
}
const response: AcceptedPreviewRecoveryResponse = {
  source_sha256: 'a'.repeat(64), content_revision: 9,
  artifact: {
    job_id: 'job-a', artifact_id: 'b'.repeat(64), document_id: 'resume-a', content_revision: 9,
    source_sha256: 'a'.repeat(64), branch: 'draft', owner_epoch: 2, compiler: 'pdflatex',
    settings_sha256: 'c'.repeat(64), pdf_sha256: 'd'.repeat(64), pdf_size: 100,
    page_count: 1, preview_url: '/download/job-a/preview/fixture',
  },
}

describe('accepted artifact recovery', () => {
  it('accepts an exact owner/document/source/revision artifact', () => {
    expect(isMatchingAcceptedArtifact(response, identity, 'a'.repeat(64))).toBe(true)
  })

  it.each([
    { content_revision: 8 },
    { source_sha256: 'e'.repeat(64) },
    { document_id: 'resume-b' },
    { branch: 'candidate' as const },
  ])('rejects a stale or non-draft artifact: %o', (change) => {
    const stale = { ...response, artifact: { ...response.artifact!, ...change } } as AcceptedPreviewRecoveryResponse
    expect(isMatchingAcceptedArtifact(stale, identity, 'a'.repeat(64))).toBe(false)
  })

  it.each([
    { ownerId: 'owner-b' },
    { resumeId: 'resume-b' },
    { generation: 4 },
    { source: 'edited source' },
    { contentRevision: 10 },
  ])('rejects a response after live identity changes: %o', async (change) => {
    let current: AcceptedPreviewRecoveryIdentity | null = { ...identity }
    let finish!: (value: AcceptedPreviewRecoveryResponse) => void
    const delayed = new Promise<AcceptedPreviewRecoveryResponse>((resolve) => { finish = resolve })
    const pending = resolveCurrentAcceptedPreviewRecovery(identity, () => current, delayed)
    current = { ...identity, ...change }
    finish(response)
    await expect(pending).resolves.toBeNull()
  })

  it('permits initial preview admission only after a definite no-artifact response', () => {
    expect(shouldSubmitInitialPreview('none')).toBe(true)
    expect(shouldSubmitInitialPreview('found')).toBe(false)
    expect(shouldSubmitInitialPreview('unavailable')).toBe(false)
  })

  it('keeps the same authenticated document generation current', () => {
    expect(isCurrentAcceptedPreviewRecovery(identity, { ...identity })).toBe(true)
  })

  it('retries a 503 once after a bounded Retry-After and returns the second read', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 503, headers: { 'Retry-After': '2' } }))
      .mockResolvedValueOnce(new Response('ok', { status: 200 }))
    const pending = fetchAcceptedArtifact(request, async response => response)
    await vi.advanceTimersByTimeAsync(2_000)
    const response = await pending
    expect(response.status).toBe(200)
    expect(request).toHaveBeenCalledTimes(2)
    expect(request.mock.calls.every(([signal]) => signal instanceof AbortSignal)).toBe(true)
  })

  it.each([null, 'not-a-date', '3'])('does not retry 503 with an absent or over-budget Retry-After: %s', async (header) => {
    const request = vi.fn().mockResolvedValue(new Response('', {
      status: 503, headers: header === null ? undefined : { 'Retry-After': header },
    }))
    const response = await fetchAcceptedArtifact(request, async response => response)
    expect(response.status).toBe(503)
    expect(request).toHaveBeenCalledOnce()
  })

  it('parses bounded Retry-After seconds and HTTP dates', () => {
    expect(retryAfterMilliseconds('2', 1_000)).toBe(2_000)
    expect(retryAfterMilliseconds(new Date(3_000).toUTCString(), 1_000)).toBeGreaterThan(0)
    expect(retryAfterMilliseconds('-1', 1_000)).toBeNull()
    expect(retryAfterMilliseconds('invalid', 1_000)).toBeNull()
  })

  it('aborts a hung accepted-artifact request at the overall deadline', async () => {
    const request = vi.fn((signal: AbortSignal) => new Promise<Response>((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    }))
    const pending = fetchAcceptedArtifact(request, async response => response)
    const rejected = expect(pending).rejects.toThrow()
    await vi.advanceTimersByTimeAsync(ACCEPTED_ARTIFACT_RECOVERY_TIMEOUT_MS)
    await rejected
    expect(request).toHaveBeenCalledOnce()
  })

  it('settles at the deadline even when authentication or transport ignores abort forever', async () => {
    const request = vi.fn(() => new Promise<Response>(() => {}))
    const parse = vi.fn(async (response: Response) => response)
    const pending = fetchAcceptedArtifact(request, parse)
    const rejected = expect(pending).rejects.toThrow('timed out')
    await vi.advanceTimersByTimeAsync(ACCEPTED_ARTIFACT_RECOVERY_TIMEOUT_MS)
    await rejected
    expect(request).toHaveBeenCalledOnce()
    expect(parse).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('includes an unresponsive response-body parser in the same overall deadline', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 503, headers: { 'Retry-After': '2' } }))
      .mockResolvedValueOnce(new Response('', { status: 200 }))
    const parse = vi.fn(() => new Promise<never>(() => {}))
    const pending = fetchAcceptedArtifact(request, parse)
    const rejected = expect(pending).rejects.toThrow('timed out')
    await vi.advanceTimersByTimeAsync(ACCEPTED_ARTIFACT_RECOVERY_TIMEOUT_MS)
    await rejected
    expect(request).toHaveBeenCalledTimes(2)
    expect(parse).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each([200, 503])('rejects a late %i response after timeout even when the transport ignores abort', async status => {
    let finish!: (response: Response) => void
    const request = vi.fn(() => new Promise<Response>(resolve => { finish = resolve }))
    const parse = vi.fn(async (response: Response) => response)
    const pending = fetchAcceptedArtifact(request, parse)
    const rejected = expect(pending).rejects.toThrow()
    await vi.advanceTimersByTimeAsync(ACCEPTED_ARTIFACT_RECOVERY_TIMEOUT_MS)
    finish(new Response('', { status, headers: status === 503 ? { 'Retry-After': '0' } : undefined }))
    await rejected
    expect(request).toHaveBeenCalledOnce()
    expect(parse).not.toHaveBeenCalled()
  })

  it('cancels the Retry-After wait when the caller abandons this identity', async () => {
    const controller = new AbortController()
    const request = vi.fn().mockResolvedValue(new Response('', { status: 503, headers: { 'Retry-After': '2' } }))
    const pending = fetchAcceptedArtifact(request, async response => response, controller.signal)
    await vi.advanceTimersByTimeAsync(0)
    expect(vi.getTimerCount()).toBe(2)
    controller.abort()
    await expect(pending).rejects.toThrow()
    expect(request).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not start an operation abandoned before its dispatch microtask', async () => {
    const controller = new AbortController()
    const request = vi.fn().mockResolvedValue(new Response('', { status: 200 }))
    const parse = vi.fn(async (response: Response) => response)
    const pending = fetchAcceptedArtifact(request, parse, controller.signal)
    controller.abort()
    await expect(pending).rejects.toThrow()
    expect(request).not.toHaveBeenCalled()
    expect(parse).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })
})
