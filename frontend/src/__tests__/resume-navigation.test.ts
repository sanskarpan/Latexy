import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { ResumeResponse } from '@/lib/api-client'
import { cloneStructuredResume } from '@/lib/resume-builder'
import { resumeEditorHref } from '@/lib/resume-navigation'

const activeBuilder = {
  id: 'resume-1', user_id: 'owner-1', access_role: 'owner',
  content_source: 'builder', builder_status: 'active',
  selected_template_id: 'template-1', structured_content: cloneStructuredResume(),
  parent_resume_id: null, document_type: 'resume',
} satisfies Parameters<typeof resumeEditorHref>[0]

describe('workspace résumé continuation routes', () => {
  it('returns the authenticated owner to the active guided builder', () => {
    expect(resumeEditorHref(activeBuilder, 'owner-1')).toBe('/workspace/builder/resume-1')
  })

  it('supports older owner payloads without an access role, while still checking ownership', () => {
    expect(resumeEditorHref({ ...activeBuilder, access_role: undefined }, 'owner-1')).toBe('/workspace/builder/resume-1')
    expect(resumeEditorHref({ ...activeBuilder, access_role: undefined }, 'another-user')).toBe('/workspace/resume-1/edit')
  })

  it.each(['editor', 'commenter', 'viewer'] as const)('keeps a collaborator with role %s in the permission-aware editor', role => {
    expect(resumeEditorHref({ ...activeBuilder, access_role: role }, 'owner-1')).toBe('/workspace/resume-1/edit')
  })

  it.each([null, '', 'another-user'])('does not infer ownership for identity %s', identity => {
    expect(resumeEditorHref(activeBuilder, identity)).toBe('/workspace/resume-1/edit')
  })

  it('keeps both parent-linked and explicitly rendered variants in the variant editor', () => {
    expect(resumeEditorHref({ ...activeBuilder, parent_resume_id: 'master-1' }, 'owner-1')).toBe('/workspace/resume-1/edit')
    expect(resumeEditorHref(activeBuilder, 'owner-1', true)).toBe('/workspace/resume-1/edit')
  })

  it.each([
    { content_source: 'manual_latex' }, { content_source: 'upload' },
    { builder_status: 'detached' }, { builder_status: undefined },
    { selected_template_id: null }, { structured_content: null },
    { document_type: 'presentation' },
  ] satisfies Partial<ResumeResponse>[])('preserves the existing editor for unsupported builder state %j', overrides => {
    expect(resumeEditorHref({ ...activeBuilder, ...overrides }, 'owner-1')).toBe('/workspace/resume-1/edit')
  })

  it('encodes document identities as a single route segment', () => {
    expect(resumeEditorHref({ ...activeBuilder, id: 'doc/with spaces' }, 'owner-1')).toBe('/workspace/builder/doc%2Fwith%20spaces')
  })

  it('uses the same guarded route for grid Edit, list title and list Edit', () => {
    const workspace = readFileSync(new URL('../app/workspace/page.tsx', import.meta.url), 'utf8')
    expect(workspace).toContain('href={resumeEditorHref(resume, workspaceOwnerId, isVariant)}')
    expect(workspace.match(/href=\{resumeEditorHref\(resume, workspaceOwnerId\)\}/g)).toHaveLength(2)
    expect(workspace).toContain('href={resumeEditorHref(r, workspaceOwnerId)}')
    expect(workspace).toContain('href={`/workspace/${variant.id}/edit`}')
    const builder = readFileSync(new URL('../app/workspace/builder/[resumeId]/page.tsx', import.meta.url), 'utf8')
    expect(builder).toContain('href={`/workspace/${resumeId}/edit`}')
  })
})
