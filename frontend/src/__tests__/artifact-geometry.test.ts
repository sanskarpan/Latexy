import { describe, expect, it } from 'vitest'
import { editableGeometry } from '@/lib/artifact-geometry'
import { jobStreamReducer, initialState } from '@/hooks/useJobStream.reducer'
import type { ArtifactReadyEvent } from '@/lib/event-types'
import type { ArtifactGeometry, ResumeEngineDocument } from '@/lib/resume-engine-types'

const artifact: ArtifactReadyEvent = { type: 'artifact.ready', event_id: 'ready', job_id: 'job', timestamp: 1, sequence: 4,
  artifact_id: 'artifact', source_sha256: 'source', pdf_sha256: 'pdf', content_revision: 3, document_id: 'document',
  branch: 'draft', owner_epoch: 2, compiler: 'pdflatex', settings_sha256: 'settings', pdf_size: 100, page_count: 1, preview_url: '/preview' }
const document: ResumeEngineDocument = { document_id: 'document', source_mode: 'managed', content_revision: 3,
  source_sha256: 'source', structured_version: 1, template_id: 'template', opaque_blocks: [],
  nodes: [{ node_id: 'node', node_revision: 'node-revision', text: 'Built Python tools', section: 'Experience', kind: 'bullet',
    source_span: { start: 10, end: 28 }, editable: true, ai_editable: true }] }
const geometry: ArtifactGeometry = { schema_version: 1, coordinate_system: 'pdf_points_top_left', document_id: 'document',
  artifact_id: 'artifact', source_sha256: 'source', pdf_sha256: 'pdf', content_revision: 3, branch: 'draft',
  pages: [{ page: 1, width: 600, height: 800, rotation: 0 }],
  boxes: [{ node_id: 'node', node_revision: 'node-revision', text: 'Built Python tools', source_span: { start: 10, end: 28 }, page: 1, x: 30, y: 60, width: 200, height: 12 }] }

describe('immutable PDF editing guards', () => {
  it('enables a verified node only for the displayed accepted source revision', () => {
    expect(editableGeometry(artifact, geometry, document, 'source')?.boxes).toHaveLength(1)
  })
  it.each(['artifact_id', 'source_sha256', 'pdf_sha256', 'document_id', 'branch'])('rejects mismatched %s', (field) => {
    expect(editableGeometry(artifact, { ...geometry, [field]: 'different' }, document, 'source')).toBeNull()
  })
  it('rejects unaccepted proposals, stale drafts and document revisions', () => {
    expect(editableGeometry({ ...artifact, branch: 'candidate' }, { ...geometry, branch: 'candidate' }, document, 'source')).toBeNull()
    expect(editableGeometry(artifact, geometry, document, 'newer-local-source')).toBeNull()
    expect(editableGeometry(artifact, { ...geometry, content_revision: 2 }, document, 'source')).toBeNull()
  })
  it('omits ambiguous, rotated, wrong-node and out-of-page boxes', () => {
    expect(editableGeometry(artifact, { ...geometry, pages: [{ ...geometry.pages[0], rotation: 90 }] }, document, 'source')?.boxes).toEqual([])
    expect(editableGeometry(artifact, { ...geometry, boxes: [{ ...geometry.boxes[0], node_revision: 'stale' }] }, document, 'source')?.boxes).toEqual([])
    expect(editableGeometry(artifact, { ...geometry, boxes: [{ ...geometry.boxes[0], width: 1000 }] }, document, 'source')?.boxes).toEqual([])
  })
  it('refuses absent artifact revision and unverified source span or text', () => {
    expect(editableGeometry({ ...artifact, document_id: 'other' }, geometry, document, 'source')).toBeNull()
    expect(editableGeometry({ ...artifact, content_revision: null }, geometry, document, 'source')).toBeNull()
    expect(editableGeometry(artifact, { ...geometry, boxes: [{ ...geometry.boxes[0], text: 'different' }] }, document, 'source')?.boxes).toEqual([])
    expect(editableGeometry(artifact, geometry, { ...document, nodes: [{ ...document.nodes[0], source_span: null }] }, 'source')?.boxes).toEqual([])
  })
  it('preview readiness keeps processing and does not accept or complete a job', () => {
    const state = jobStreamReducer({ ...initialState, status: 'processing', percent: 70 }, artifact)
    expect(state.status).toBe('processing'); expect(state.percent).toBe(70)
    expect(state.artifact).toEqual(artifact); expect(state.pdfJobId).toBeNull()
    expect(jobStreamReducer({ ...state, status: 'cancelled' }, artifact).artifact).toEqual(artifact)
    expect(jobStreamReducer({ ...state, status: 'failed', artifact: null }, artifact).artifact).toBeNull()
    expect(jobStreamReducer(state, { ...artifact, artifact_id: 'old-attempt', owner_epoch: 1 }).artifact).toEqual(artifact)
  })
})
