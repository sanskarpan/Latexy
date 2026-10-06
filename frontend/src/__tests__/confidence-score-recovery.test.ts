import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const hook = readFileSync(new URL('../hooks/useConfidenceScore.ts', import.meta.url), 'utf8')
const panel = readFileSync(new URL('../components/ConfidenceScorePanel.tsx', import.meta.url), 'utf8')
const editor = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')

describe('confidence-score recovery', () => {
  it('invalidates stale results and exposes request failures', () => {
    expect(hook).toContain('requestIdRef.current += 1')
    expect(hook).toContain('setResult(null)')
    expect(hook).toContain('Failed to calculate quality score')
    expect(hook).toContain('return { result, loading, error, refetch }')
  })

  it('renders an accessible retry and wires the hook error into the panel', () => {
    expect(panel).toContain('error && !score')
    expect(panel).toContain('Retry score')
    expect(panel).toContain('role="alert"')
    expect(editor).toContain('error: confidenceError')
    expect(editor).toContain('error={confidenceError}')
  })
})
