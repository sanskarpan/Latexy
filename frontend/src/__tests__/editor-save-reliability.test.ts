import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const EDITOR = readFileSync(
  new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url),
  'utf8',
)
const VISUAL_EDITOR = readFileSync(
  new URL('../components/VisualResumeEditor.tsx', import.meta.url),
  'utf8',
)

describe('editor save reliability', () => {
  it('rejects invalid titles before manual or automatic API writes', () => {
    expect(EDITOR).toContain("if (!title.trim()) {")
    expect(EDITOR).toContain("if (!title.trim() || title.length > 255) {")
    expect(EDITOR).toContain('maxLength={255}')
  })

  it('surfaces backend save errors instead of swallowing them', () => {
    expect(EDITOR).toContain("setSaveError(error instanceof Error ? error.message : 'Autosave failed')")
    expect(EDITOR).toContain('saveError ? `Save failed: ${saveError}`')
    expect(EDITOR).not.toContain('// Silent — manual Save or the next change will retry.')
  })

  it('does not persist a transitional empty Monaco snapshot over React state', () => {
    expect(EDITOR).toContain('const content = editorRef.current?.getValue() || latexContent')
    expect(EDITOR).not.toContain('const content = editorRef.current?.getValue() ?? latexContent')
  })

  it('guards IndexedDB draft and compile queue writes', () => {
    expect(EDITOR).toContain("toast.error('Could not save the offline draft')")
    expect(EDITOR).toContain("'Could not queue the offline compile'")
  })

  it('restores pending drafts after refresh and supports a fully offline reload', () => {
    expect(EDITOR).toContain('getDraft(ownerAtStart, resumeId)')
    expect(EDITOR).toContain("localDraft?.syncStatus === 'pending'")
    expect(EDITOR).toContain('pendingDraft?.latexContent ?? data.latex_content')
    expect(EDITOR).toContain('if (!sessionData && !offlineDraftLoaded && !offlinePdfLoaded) return null')
    expect(EDITOR).toContain('getPendingDrafts(sessionUserId)')
    expect(EDITOR).toContain('deleteDraftIfUnchanged(draft)')
    expect(EDITOR).not.toContain('deleteDraft(sessionUserId, draft.resumeId)')

    const authGuard = readFileSync(
      new URL('../hooks/useRequireAuth.ts', import.meta.url),
      'utf8',
    )
    expect(authGuard).toContain("typeof navigator !== 'undefined' && !navigator.onLine")
  })

  it('does not flush and delete a pending draft before initial restoration', () => {
    expect(EDITOR).toContain('if (isLoading || !sessionUserId) return')
    expect(EDITOR).toContain('const count = await pendingDraftCount(sessionUserId)')
    expect(EDITOR).toContain('if (isActive()) setOfflinePendingCount(count)')
    expect(EDITOR).toContain('[isCurrentOfflinePdfIdentity, isOnline, isLoading, offlinePdfOwnerId, resumeId, sessionUserId]')
  })

  it('documents the browser-profile boundary for cold offline recovery', () => {
    expect(EDITOR).toContain('unlocked browser')
    expect(EDITOR).toContain('confirmed login/account switch and logout perform purges')
  })

  it('shows recovery actions when the resume or offline draft cannot load', () => {
    expect(EDITOR).toContain('Resume could not be loaded')
    expect(EDITOR).toContain('No offline draft is available for this resume.')
    expect(EDITOR).toContain('onClick={() => window.location.reload()}')
    expect(EDITOR).not.toContain("toast.error('Failed to load resume')")
  })

  it('rebuilds the visual document when visual mode was persisted across reload', () => {
    expect(EDITOR).toContain("localStorage.getItem(`latexy_editor_mode_${resumeId}`) === 'source' ? 'source' : 'wysiwyg'")
    expect(EDITOR).toContain('localStorage.setItem(`latexy_editor_mode_${resumeId}`, mode)')
    expect(EDITOR).toContain('<VisualResumeEditor value={latexContent} onChange={setLatexContent} readOnly={!canEditDocument} />')
    expect(VISUAL_EDITOR).toContain('useMemo(() => projectVisualResume(value), [value])')
  })

  it('retains the last successful PDF while a replacement compile runs or fails', () => {
    expect(EDITOR).toContain('Keep the last successful preview while a replacement compiles')
    expect(EDITOR).toContain('activePdfJobId.current ?? ownedCompileJobId ?? ownedAiJobId)')
    expect(EDITOR).toContain('const id = ownsRenderedJobState')
    expect(EDITOR).toContain('useJobStream(ownedCompileJobId)')
    expect(EDITOR).not.toContain('if (anyRunning && pdfUrlRef.current)')
  })

  it('exports the live editor buffer and wires PDF export to the latest successful artifact', () => {
    expect(EDITOR).toContain('latexContent={latexContent}')
    expect(EDITOR).toContain('onPdfExport={handleDownload}')

    const dropdown = readFileSync(
      new URL('../components/ExportDropdown.tsx', import.meta.url),
      'utf8',
    )
    expect(dropdown.indexOf('if (latexContent !== undefined)'))
      .toBeLessThan(dropdown.indexOf('else if (resumeId)'))
  })
})
