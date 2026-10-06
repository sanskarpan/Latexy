import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const panel = readFileSync(new URL('../components/ReviewCommentsPanel.tsx', import.meta.url), 'utf8')
const shareModal = readFileSync(new URL('../components/ShareResumeModal.tsx', import.meta.url), 'utf8')
const publicPage = readFileSync(new URL('../app/r/[token]/page.tsx', import.meta.url), 'utf8')
const surface = readFileSync(new URL('../components/ReviewablePdfSurface.tsx', import.meta.url), 'utf8')
const editorPage = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')

describe('peer review UI safety and capability gating', () => {
  it('renders comment content as React text and never injects HTML', () => {
    expect(panel).toContain('{comment.content}')
    expect(panel).not.toContain('dangerouslySetInnerHTML')
  })

  it('shows only pseudonymous labels and honest source anchors', () => {
    expect(panel).toContain('{comment.reviewer_label}')
    expect(panel).toContain('source line')
    expect(panel).not.toContain('author_email')
    expect(panel).not.toContain('author_id')
  })

  it('gates the public panel on the server capability', () => {
    expect(publicPage).toContain('data.review_comments && token')
    expect(publicPage).toContain('<ReviewCommentsPanel shareToken={token} pdfUrl={data.pdf_url}')
  })

  it('offers an explicit owner toggle without sending an omitted false', () => {
    expect(shareModal).toContain('Allow review comments')
    expect(shareModal).toContain('reviewComments ?? undefined')
    expect(shareModal).toContain('Update review access')
  })

  it('requires a sticky anchor for PDF-backed public comments while preserving legacy no-PDF writes', () => {
    expect(panel).toContain("Select a point on the document before posting feedback.")
    expect(panel).toContain('Boolean(pdfUrl && !selectedAnchor)')
    expect(panel).toContain('Legacy source line (optional)')
  })

  it('clears stale capability state and ignores out-of-order requests', () => {
    expect(panel).toContain('identityGeneration')
    expect(panel).toContain('setComments([])')
    expect(panel).toContain("setContent('')")
    expect(panel).toContain("setLineNumber('')")
    expect(panel).toContain("setSectionTag('')")
    expect(panel).toContain('setSubmitting(false)')
    expect(panel).toContain('reviewRequestIsCurrent(generation, identityGeneration.current)')
    expect(panel).toContain('{capabilityInvalid ? null : loading ? (')
  })

  it('keeps editor review access separate from ordinary comments and chat', () => {
    expect(editorPage).toContain("rightTab === 'review'")
    expect(editorPage).toContain("canResolve={collabRole === 'owner' || collabRole === 'editor'}")
    expect(surface).toContain('Existing dots open their comment.')
  })
})
