import { describe, expect, it } from 'vitest'
import { canExportArtifact, type RecoveredAcceptedArtifactExportContext } from '@/lib/artifact-policy'
import type { RenderArtifact } from '@/lib/event-types'
const artifact = { branch: 'draft', source_sha256: 'current' } as RenderArtifact

describe('PDF export authority', () => {
  it('allows only the successful completed job for the current draft', () => {
    expect(canExportArtifact(artifact, 'current', 'job', 'completed', 'job')).toBe(true)
    for (const status of ['queued', 'processing', 'failed', 'cancelled', 'idle'])
      expect(canExportArtifact(artifact, 'current', 'job', status, 'job')).toBe(false)
    expect(canExportArtifact(artifact, 'newer', 'job', 'completed', 'job')).toBe(false)
    expect(canExportArtifact(artifact, 'current', 'other', 'completed', 'job')).toBe(false)
    expect(canExportArtifact({ ...artifact, branch: 'candidate' }, 'current', 'job', 'completed', 'job')).toBe(false)
  })

  it('allows a verified current accepted artifact after recovery without a compile job', () => {
    const recovered = {
      ...artifact,
      job_id: 'accepted-job',
      artifact_id: 'a'.repeat(64),
      document_id: 'resume-a',
      content_revision: 9,
      pdf_sha256: 'b'.repeat(64),
      pdf_size: 1234,
    } as RenderArtifact & { job_id: string }
    const context: RecoveredAcceptedArtifactExportContext = {
      artifact: recovered,
      ownerId: 'owner-a', currentOwnerId: 'owner-a',
      resumeId: 'resume-a', currentResumeId: 'resume-a',
      generation: 3, currentGeneration: 3,
      source: 'current source', currentSource: 'current source',
      contentRevision: 9, currentContentRevision: 9,
      compileJobId: null, aiJobId: null, renderedJobId: 'accepted-job',
    }

    expect(canExportArtifact(recovered, 'current', null, 'idle', 'accepted-job', context)).toBe(true)
  })

  it.each([
    ['owner changed', { currentOwnerId: 'owner-b' }],
    ['resume changed', { currentResumeId: 'resume-b' }],
    ['generation changed', { currentGeneration: 4 }],
    ['source changed', { currentSource: 'edited source' }],
    ['revision changed', { currentContentRevision: 10 }],
    ['compile active', { compileJobId: 'new-compile' }],
    ['AI active', { aiJobId: 'new-ai' }],
    ['rendered job changed', { renderedJobId: 'newer-job' }],
  ])('denies recovered export when %s', (_label, change) => {
    const recovered = {
      ...artifact,
      job_id: 'accepted-job', artifact_id: 'a'.repeat(64), document_id: 'resume-a',
      content_revision: 9, pdf_sha256: 'b'.repeat(64), pdf_size: 1234,
    } as RenderArtifact & { job_id: string }
    const context: RecoveredAcceptedArtifactExportContext = {
      artifact: recovered,
      ownerId: 'owner-a', currentOwnerId: 'owner-a', resumeId: 'resume-a', currentResumeId: 'resume-a',
      generation: 3, currentGeneration: 3, source: 'current source', currentSource: 'current source',
      contentRevision: 9, currentContentRevision: 9, compileJobId: null, aiJobId: null,
      renderedJobId: 'accepted-job', ...change,
    }

    expect(canExportArtifact(recovered, 'current', null, 'idle', 'accepted-job', context)).toBe(false)
    expect(canExportArtifact({ ...recovered, source_sha256: 'old' }, 'current', null, 'idle', 'accepted-job', context)).toBe(false)
    expect(canExportArtifact({ ...recovered, artifact_id: 'c'.repeat(64) }, 'current', null, 'idle', 'accepted-job', context)).toBe(false)
    expect(canExportArtifact({ ...recovered, branch: 'candidate' }, 'current', null, 'idle', 'accepted-job', context)).toBe(false)
  })
})
