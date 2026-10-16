import { describe, expect, it } from 'vitest'
import {
  isCurrentAcceptedPreviewRecovery,
  isMatchingAcceptedArtifact,
  resolveCurrentAcceptedPreviewRecovery,
  shouldSubmitInitialPreview,
  type AcceptedPreviewRecoveryIdentity,
  type AcceptedPreviewRecoveryResponse,
} from '@/lib/accepted-artifact-recovery'

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
})
