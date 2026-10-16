import type { RenderArtifact } from './event-types'

export interface RecoveredAcceptedArtifactExportContext {
  artifact: RenderArtifact & { job_id: string }
  ownerId: string | null
  currentOwnerId: string | null
  resumeId: string
  currentResumeId: string
  generation: number
  currentGeneration: number
  source: string
  currentSource: string
  contentRevision: number | null
  currentContentRevision: number | null
  compileJobId: string | null
  aiJobId: string | null
  renderedJobId: string | null
}

export function canExportRecoveredAcceptedArtifact(
  artifact: RenderArtifact & { job_id: string }, currentSourceHash: string | null,
  jobId: string | null, status: string, artifactJobId: string,
  recovery: RecoveredAcceptedArtifactExportContext | null,
): boolean {
  if (!recovery || !currentSourceHash || jobId !== null || status !== 'idle'
      || recovery.ownerId === null || recovery.ownerId !== recovery.currentOwnerId
      || recovery.resumeId !== recovery.currentResumeId
      || recovery.generation !== recovery.currentGeneration
      || recovery.source !== recovery.currentSource
      || recovery.contentRevision === null
      || recovery.contentRevision !== recovery.currentContentRevision
      || recovery.compileJobId !== null || recovery.aiJobId !== null
      || recovery.renderedJobId !== recovery.artifact.job_id) return false

  return artifact.branch === 'draft'
    && artifact.job_id === artifactJobId
    && artifact.job_id === recovery.artifact.job_id
    && artifact.artifact_id === recovery.artifact.artifact_id
    && artifact.source_sha256 === currentSourceHash
    && artifact.source_sha256 === recovery.artifact.source_sha256
    && artifact.document_id === recovery.resumeId
    && artifact.content_revision === recovery.contentRevision
    && artifact.pdf_sha256 === recovery.artifact.pdf_sha256
    && artifact.pdf_size === recovery.artifact.pdf_size
}

export function canExportArtifact(artifact: RenderArtifact, currentSourceHash: string | null,
  jobId: string | null, status: string, artifactJobId: string,
  recovery: RecoveredAcceptedArtifactExportContext | null = null): boolean {
  const completedJobAllowsExport = artifact.branch === 'draft' && artifact.source_sha256 === currentSourceHash
    && jobId === artifactJobId && status === 'completed'
  if (completedJobAllowsExport) return true
  return 'job_id' in artifact && canExportRecoveredAcceptedArtifact(
    artifact as RenderArtifact & { job_id: string }, currentSourceHash, jobId, status, artifactJobId, recovery)
}
