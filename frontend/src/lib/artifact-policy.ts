import type { RenderArtifact } from './event-types'

export function canExportArtifact(artifact: RenderArtifact, currentSourceHash: string | null,
  jobId: string | null, status: string, artifactJobId: string): boolean {
  return artifact.branch === 'draft' && artifact.source_sha256 === currentSourceHash
    && jobId === artifactJobId && status === 'completed'
}
