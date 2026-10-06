import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const PANEL_SOURCE = readFileSync(
  new URL('../components/ReferencesPanel.tsx', import.meta.url),
  'utf8',
)

describe('saved reference-library recovery', () => {
  it('separates a metadata outage from an empty saved library and offers retry', () => {
    expect(PANEL_SOURCE).toContain('setLibraryLoadError(')
    expect(PANEL_SOURCE).toContain('Saved references could not be loaded.')
    expect(PANEL_SOURCE).toContain('role="alert"')
    expect(PANEL_SOURCE).toContain('setLibraryReloadNonce(value => value + 1)')
  })

  it('restores the optimistic clear when persistence fails', () => {
    expect(PANEL_SOURCE).toContain('const previousBibTeX = importedBibTeX')
    expect(PANEL_SOURCE).toContain('await apiClient.clearResumeBibTeX(resumeId)')
    expect(PANEL_SOURCE).toContain('setImportedBibTeX(previousBibTeX)')
  })

  it('does not turn reference-provider status outages into disconnected states', () => {
    expect(PANEL_SOURCE).not.toContain("catch(() => setStatus({ connected: false")
    expect(PANEL_SOURCE).toContain('Retry Zotero status')
    expect(PANEL_SOURCE).toContain('Retry Mendeley status')
    expect(PANEL_SOURCE).toContain('status === null ?')
    expect(PANEL_SOURCE).toContain('The Zotero sign-in popup was blocked.')
    expect(PANEL_SOURCE).toContain('The Mendeley sign-in popup was blocked.')
  })
})
