import { readFileSync } from 'node:fs'
import { describe, expect, it, vi } from 'vitest'
import {
  EDITOR_SYNCTEX_DEDUPE_WINDOW_MS,
  EDITOR_TOGGLE_DEDUPE_WINDOW_MS,
  buildEditorTelemetryEvent,
  createEditorTelemetryClient,
  sanitizeEditorRoute,
} from '@/lib/editor-mode-telemetry'

const DOCUMENT_HASH = 'a'.repeat(64)
const OTHER_HASH = 'b'.repeat(64)

function client({
  consent = 'granted' as 'granted' | 'denied' | null,
  now = 1_000,
} = {}) {
  const send = vi.fn()
  const telemetry = createEditorTelemetryClient({
    readConsent: () => consent,
    hashDocument: async () => DOCUMENT_HASH,
    now: () => now,
    send,
    route: () => '/workspace/:resumeId/edit',
  })
  return { telemetry, send }
}

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('editor telemetry privacy boundary', () => {
  it('emits only allowlisted keys and never source, prompts or filenames', () => {
    const event = buildEditorTelemetryEvent('editor_mode_selected', {
      mode: 'wysiwyg',
      route: '/workspace/private-resume-2077/edit?token=secret',
      documentHash: DOCUMENT_HASH,
      eventId: 'editor-2077-event',
      // Hostile extras are not part of the typed contract.
      latex_source: '\\section{Private Candidate}',
      prompt: 'secret prompt',
      filename: 'private-resume-2077.tex',
      document_id: 'resume_2077_private',
    } as never)

    expect(event).toEqual({
      event_type: 'editor_mode_selected',
      mode: 'wysiwyg',
      route: '/workspace/:resumeId/edit',
      document_hash: DOCUMENT_HASH,
      event_id: 'editor-2077-event',
    })
    expect(Object.keys(event ?? {}).sort()).toEqual([
      'document_hash',
      'event_id',
      'event_type',
      'mode',
      'route',
    ])
    const serialized = JSON.stringify(event).toLowerCase()
    expect(serialized).not.toContain('private')
    expect(serialized).not.toContain('latex')
    expect(serialized).not.toContain('prompt')
    expect(serialized).not.toContain('resume_2077')
  })

  it('rejects unknown modes, event types, directions and non-hash document ids', () => {
    expect(
      buildEditorTelemetryEvent('editor_mode_selected', {
        mode: 'whiteboard',
        documentHash: DOCUMENT_HASH,
      }),
    ).toBeNull()
    expect(
      buildEditorTelemetryEvent('unknown_event', {
        mode: 'source',
        documentHash: DOCUMENT_HASH,
      }),
    ).toBeNull()
    expect(
      buildEditorTelemetryEvent('synctex_used', {
        mode: 'source',
        documentHash: DOCUMENT_HASH,
        direction: 'sideways',
      }),
    ).toBeNull()
    expect(
      buildEditorTelemetryEvent('editor_mode_selected', {
        mode: 'source',
        documentHash: 'private-resume-2077',
      }),
    ).toBeNull()
  })

  it('includes the toggle state and SyncTeX direction only for their events', () => {
    expect(
      buildEditorTelemetryEvent('auto_compile_toggled', {
        mode: 'pdf',
        documentHash: DOCUMENT_HASH,
        enabled: false,
        eventId: 'toggle-2077',
      }),
    ).toEqual({
      event_type: 'auto_compile_toggled',
      mode: 'pdf',
      route: '/other',
      document_hash: DOCUMENT_HASH,
      event_id: 'toggle-2077',
      enabled: false,
    })
    expect(
      buildEditorTelemetryEvent('synctex_used', {
        mode: 'source',
        documentHash: DOCUMENT_HASH,
        direction: 'pdf_to_source',
        eventId: 'sync-2077',
      }),
    ).toEqual({
      event_type: 'synctex_used',
      mode: 'source',
      route: '/other',
      document_hash: DOCUMENT_HASH,
      event_id: 'sync-2077',
      direction: 'pdf_to_source',
    })
  })

  it('buckets dynamic editor paths into a fixed route vocabulary', () => {
    expect(sanitizeEditorRoute('/workspace/abc-123/edit')).toBe(
      '/workspace/:resumeId/edit',
    )
    expect(sanitizeEditorRoute('/workspace/abc-123/edit?token=share-secret')).toBe(
      '/workspace/:resumeId/edit',
    )
    expect(sanitizeEditorRoute('/workspace/abc-123')).toBe('/workspace/:resumeId')
    expect(sanitizeEditorRoute('/settings')).toBe('/settings')
    expect(sanitizeEditorRoute('/workspace/abc-123/unknown-panel')).toBe('/other')
    expect(sanitizeEditorRoute('https://evil.example/workspace/id/edit')).toBe('/other')
  })
})

describe('editor telemetry consent and dedupe', () => {
  it('sends nothing without analytics consent', async () => {
    const { telemetry, send } = client({ consent: 'denied' })
    expect(
      telemetry.selectMode('source', { documentId: 'resume-2077' }),
    ).toBe(false)
    expect(
      telemetry.toggleAutoCompile(true, { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(false)
    expect(
      telemetry.synctex('source_to_pdf', { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(false)
    await flush()
    expect(send).not.toHaveBeenCalled()
  })

  it('sends a mode selection only once within the repeat window', async () => {
    const { telemetry, send } = client()
    expect(
      telemetry.selectMode('source', { documentId: 'resume-2077' }),
    ).toBe(true)
    expect(
      telemetry.selectMode('source', { documentId: 'resume-2077' }),
    ).toBe(false)
    await flush()
    expect(send).toHaveBeenCalledTimes(1)
    expect(send.mock.calls[0][0][0].document_hash).toBe(DOCUMENT_HASH)
  })

  it('deduplicates identical toggle state and records a state change', async () => {
    let now = 1_000
    const send = vi.fn()
    const telemetry = createEditorTelemetryClient({
      readConsent: () => 'granted',
      hashDocument: async () => DOCUMENT_HASH,
      now: () => now,
      send,
      route: () => '/workspace/:resumeId/edit',
    })

    expect(
      telemetry.toggleAutoCompile(true, { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(true)
    expect(
      telemetry.toggleAutoCompile(true, { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(false)
    await flush()
    expect(send).toHaveBeenCalledTimes(1)
    expect(send.mock.calls[0][0][0].enabled).toBe(true)

    now += 1
    expect(
      telemetry.toggleAutoCompile(false, { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(true)
    await flush()
    expect(send).toHaveBeenCalledTimes(2)
    expect(send.mock.calls[1][0][0].enabled).toBe(false)

    now += EDITOR_TOGGLE_DEDUPE_WINDOW_MS
    expect(
      telemetry.toggleAutoCompile(false, { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(true)
    await flush()
    expect(send).toHaveBeenCalledTimes(3)
  })

  it('deduplicates duplicate SyncTeX jumps inside the short window', async () => {
    let now = 1_000
    const send = vi.fn()
    const telemetry = createEditorTelemetryClient({
      readConsent: () => 'granted',
      hashDocument: async () => DOCUMENT_HASH,
      now: () => now,
      send,
    })

    expect(
      telemetry.synctex('pdf_to_source', { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(true)
    expect(
      telemetry.synctex('pdf_to_source', { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(false)
    now += EDITOR_SYNCTEX_DEDUPE_WINDOW_MS + 1
    expect(
      telemetry.synctex('pdf_to_source', { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(true)
    expect(
      telemetry.synctex('source_to_pdf', { mode: 'source', documentId: 'resume-2077' }),
    ).toBe(true)
    await flush()
    expect(send).toHaveBeenCalledTimes(3)
  })

  it('hashes the raw document id and never sends it', async () => {
    const send = vi.fn()
    const telemetry = createEditorTelemetryClient({
      readConsent: () => 'granted',
      hashDocument: async () => OTHER_HASH,
      now: () => 1_000,
      send,
    })
    expect(
      telemetry.selectMode('pdf', { documentId: 'resume-2077-private' }),
    ).toBe(true)
    await flush()

    const payload = send.mock.calls[0][0][0]
    expect(payload.document_hash).toBe(OTHER_HASH)
    expect(JSON.stringify(payload)).not.toContain('resume-2077-private')
  })

  it('reads the shared analytics consent gate and editor handlers', () => {
    const source = readFileSync(
      new URL('../lib/editor-mode-telemetry.ts', import.meta.url),
      'utf8',
    )
    const page = readFileSync(
      new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url),
      'utf8',
    )

    expect(source).toContain('readAnalyticsConsent')
    expect(source).toContain("options.readConsent() !== 'granted'")
    expect(source).toContain("'/telemetry/editor'")
    expect(source).toContain('hashDocumentId')
    expect(source).toContain('document_hash')
    expect(page).toContain('editorModeTelemetry.selectMode')
    expect(page).toContain('editorModeTelemetry.toggleAutoCompile')
    expect(page).toContain("editorModeTelemetry.synctex('pdf_to_source'")
    expect(page).toContain("editorModeTelemetry.synctex('source_to_pdf'")
  })
})
