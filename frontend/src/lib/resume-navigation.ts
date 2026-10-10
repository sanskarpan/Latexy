import type { ResumeResponse } from './api-client'

type ResumeEditorIdentity = Pick<ResumeResponse,
  'id' | 'user_id' | 'access_role' | 'content_source' | 'builder_status' |
  'parent_resume_id' | 'selected_template_id' | 'structured_content' | 'document_type'
>

/** Continue an owner's guided draft; other document workflows retain their editor. */
export function resumeEditorHref(
  resume: ResumeEditorIdentity,
  authenticatedUserId: string | null,
  isVariant = false,
): string {
  const id = encodeURIComponent(resume.id)
  const isOwner = Boolean(authenticatedUserId) && resume.user_id === authenticatedUserId &&
    (resume.access_role === undefined || resume.access_role === 'owner')
  const canContinueBuilder = isOwner && !isVariant && !resume.parent_resume_id &&
    resume.content_source === 'builder' && resume.builder_status === 'active' &&
    Boolean(resume.selected_template_id && resume.structured_content) &&
    (!resume.document_type || resume.document_type === 'resume')
  return canContinueBuilder ? `/workspace/builder/${id}` : `/workspace/${id}/edit`
}
