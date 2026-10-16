import type { RenderArtifact } from '@/lib/event-types'

export interface AcceptedPreviewRecoveryIdentity {
  ownerId: string
  resumeId: string
  generation: number
  source: string
  contentRevision: number
}

export interface AcceptedPreviewRecoveryResponse {
  artifact: (RenderArtifact & { job_id: string }) | null
  source_sha256: string
  content_revision: number
}

export function isCurrentAcceptedPreviewRecovery(
  expected: AcceptedPreviewRecoveryIdentity,
  current: AcceptedPreviewRecoveryIdentity | null,
): boolean {
  return Boolean(current
    && current.ownerId === expected.ownerId
    && current.resumeId === expected.resumeId
    && current.generation === expected.generation
    && current.source === expected.source
    && current.contentRevision === expected.contentRevision)
}

export async function resolveCurrentAcceptedPreviewRecovery(
  expected: AcceptedPreviewRecoveryIdentity,
  getCurrent: () => AcceptedPreviewRecoveryIdentity | null,
  operation: Promise<AcceptedPreviewRecoveryResponse>,
): Promise<AcceptedPreviewRecoveryResponse | null> {
  const response = await operation
  return isCurrentAcceptedPreviewRecovery(expected, getCurrent()) ? response : null
}

export function isMatchingAcceptedArtifact(
  response: AcceptedPreviewRecoveryResponse,
  identity: AcceptedPreviewRecoveryIdentity,
  sourceSha256: string,
): response is AcceptedPreviewRecoveryResponse & { artifact: RenderArtifact & { job_id: string } } {
  const artifact = response.artifact
  return Boolean(artifact
    && response.content_revision === identity.contentRevision
    && response.source_sha256 === sourceSha256
    && artifact.document_id === identity.resumeId
    && artifact.content_revision === identity.contentRevision
    && artifact.source_sha256 === sourceSha256
    && artifact.branch === 'draft'
    && /^[a-f0-9]{64}$/.test(artifact.artifact_id)
    && /^[A-Za-z0-9_-]{1,255}$/.test(artifact.job_id))
}

export function shouldSubmitInitialPreview(recovery: 'found' | 'none' | 'unavailable'): boolean {
  return recovery === 'none'
}
