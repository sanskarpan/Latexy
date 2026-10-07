export interface ResumeEngineNode {
  node_id: string; node_revision: string; section: string; kind: string; text: string
  source_span: { start: number; end: number } | null; editable: boolean; ai_editable: boolean
  entry_id?: string | null; container_id?: string; order_child_id?: string
}

export interface ResumeEngineContainer {
  container_id: string; kind: 'sections' | 'entries' | 'bullets'; label: string
  parent_id?: string; section?: string; entry_id?: string; field?: string
  ordered_child_ids: string[]; node_ids: string[]
}

export interface ResumeEngineDocument {
  document_id: string; source_mode: 'managed' | 'imported'; content_revision: number
  source_sha256: string; structured_version: number | null; template_id: string | null
  nodes: ResumeEngineNode[]; opaque_blocks: unknown[]
  containers?: ResumeEngineContainer[]
}

export interface ArtifactGeometry {
  schema_version: number; coordinate_system: 'pdf_points_top_left'; document_id: string
  artifact_id: string; source_sha256: string; pdf_sha256: string; content_revision?: number | null
  branch: 'draft' | 'candidate'
  pages: Array<{ page: number; width: number; height: number; rotation: number }>
  boxes: Array<{ node_id: string; node_revision: string; text: string; source_span: { start: number; end: number }; page: number; x: number; y: number; width: number; height: number }>
}

export type OptimizationEffort = 'quick' | 'standard' | 'deep'
export interface SemanticPatch {
  patch_id: string; node_id: string; expected_node_revision: string; original_text: string; text: string
  reason: string; review_reason?: string; validation?: Record<string, unknown>
}
export interface OptimizationDecisions {
  patches?: Record<string, 'accepted' | 'rejected'>; complete_acceptance?: boolean
  accepted_source_sha256?: string; accepted_content_revision?: number
}
export interface SemanticOptimizationRun {
  run_id: string; document_id: string; base_revision: number; source_sha256: string
  status: 'running' | 'completed' | 'partial' | 'failed' | 'cancelled'; effort: OptimizationEffort
  job_status?: string; acceptance_ready?: boolean
  pdf_quality?: { status: 'checked' | 'unavailable'; pdf_sha256: string; source_sha256: string; page_count: number | null; warnings: string[]; checks?: Record<string, 'checked' | 'partial' | 'unavailable'> }
  document: ResumeEngineDocument; decisions: OptimizationDecisions
  result: { patches: SemanticPatch[]; warnings: string[]; missing_evidence: string[]; candidate_source_sha256: string; requirements?: { requirements: Array<{ requirement_id: string; excerpt: string }> } } | null
  budget: { cost_used?: number; usage_unknown?: boolean; requests?: number; policy?: Record<string, unknown> }
}
