import type { RenderArtifact } from './event-types'
import type { ArtifactGeometry, ResumeEngineDocument } from './resume-engine-types'

/** Geometry is a capability for the exact displayed, accepted source revision. */
export function editableGeometry(artifact: RenderArtifact | null, geometry: ArtifactGeometry | null,
  document: ResumeEngineDocument | null, currentSourceHash: string | null): ArtifactGeometry | null {
  if (!artifact || !geometry || !document || !currentSourceHash || artifact.branch !== 'draft'
      || artifact.source_sha256 !== currentSourceHash || document.source_sha256 !== currentSourceHash
      || geometry.artifact_id !== artifact.artifact_id || geometry.source_sha256 !== currentSourceHash
      || geometry.pdf_sha256 !== artifact.pdf_sha256 || geometry.branch !== artifact.branch
      || artifact.document_id !== document.document_id
      || geometry.document_id !== document.document_id
      || geometry.content_revision !== document.content_revision
      || artifact.content_revision !== document.content_revision
      || geometry.coordinate_system !== 'pdf_points_top_left') return null
  const nodes = new Map(document.nodes.filter((node) => node.editable).map((node) => [node.node_id, node]))
  const pages = new Map(geometry.pages.filter((page) => Number.isFinite(page.width) && Number.isFinite(page.height)
    && page.width > 0 && page.height > 0 && page.rotation === 0).map((page) => [page.page, page]))
  return { ...geometry, boxes: geometry.boxes.filter((box) => {
    const node = nodes.get(box.node_id)
    const page = pages.get(box.page)
    return node && node.node_revision === box.node_revision && page && node.source_span
      && box.source_span?.start === node.source_span.start && box.source_span?.end === node.source_span.end
      && box.text === node.text
      && [box.x, box.y, box.width, box.height].every(Number.isFinite)
      && box.x >= 0 && box.y >= 0 && box.width > 0 && box.height > 0
      && box.x + box.width <= page.width + .1 && box.y + box.height <= page.height + .1
  }) }
}
