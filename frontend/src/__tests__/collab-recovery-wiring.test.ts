import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const editor = readFileSync(new URL('../components/LaTeXEditor.tsx', import.meta.url), 'utf8')
const page = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')

describe('collaboration recovery integration contracts', () => {
  it('carries persisted divergence through page load to initial relay admission', () => {
    expect(page).toContain('setCollabRecoveryPaused(Boolean(pendingDraft?.collaborationPaused))')
    expect(page).toContain('collabRecoveryPaused={collabRecoveryPaused}')
    expect(editor).toContain('let preservedPreSyncDraft = collabRecoveryPausedRef.current')
    expect(editor).toContain('paused: preservedPreSyncDraft || collabRecoveryPausedRef.current')
  })

  it('refreshes pending recovery metadata before initial ticket resolves, not only after pause', () => {
    expect(editor).toContain('recoveryActiveRef.current || (!bindingRef.current && (collabPaused || collabRecoveryPaused || localEditsBeforeCollabBindingRef.current))')
    expect(editor).toContain('[collabEnabled, collabPaused, collabRecoveryPaused, collabDocumentTitle, collabSavedSource, collabSavedTitle, value]')
    expect(editor).toContain('title: metadata.title')
  })

  it('owns provider before binding and rejects late initial/reconnect tickets', () => {
    expect(editor.indexOf('providerRef.current = provider')).toBeLessThan(editor.indexOf('const bindCollabDocument'))
    expect(editor).toContain("const initialTicket = await apiClient.createWebSocketTicket('collab', collabResumeId)\n          if (!isCurrentCollab()) return")
    expect(editor).toContain('if (!isCurrentCollab() || providerRef.current !== provider) return')
    expect(editor).toContain('collabGenerationRef.current += 1')
  })

  it('uses dedicated auth-scoped refresh and preserves owner saves while F04 is off', () => {
    expect(page).toContain('useCollaborationAccessRefresh({')
    expect(page).toContain("collabRole === 'owner' || can('f04')")
  })
})
