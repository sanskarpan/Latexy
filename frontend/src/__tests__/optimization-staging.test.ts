import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

const TRY_SOURCE = readFileSync(
  fileURLToPath(new URL('../app/try/page.tsx', import.meta.url)),
  'utf8'
)
const WORKSPACE_SOURCE = readFileSync(
  fileURLToPath(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url)),
  'utf8'
)
const CHANGE_REVIEW_SOURCE = readFileSync(
  fileURLToPath(new URL('../components/ChangeReviewModal.tsx', import.meta.url)),
  'utf8'
)

const DIRECT_STREAM_MUTATIONS = [
  /\.setValue\((?:aiStream|stream)\.streamingLatex/,
  /setLatexContent\((?:aiStream|stream)\.streamingLatex/,
]

describe('optimization review staging', () => {
  test.each([
    ['trial editor', TRY_SOURCE],
    ['workspace editor', WORKSPACE_SOURCE],
  ])('%s never writes stream tokens into the live document', (_, source) => {
    for (const pattern of DIRECT_STREAM_MUTATIONS) {
      expect(source).not.toMatch(pattern)
    }
  })

  test('trial editor exposes explicit review, discard, and apply controls', () => {
    expect(TRY_SOURCE).toContain('setStagedOptimization(stream.streamingLatex)')
    expect(TRY_SOURCE).toContain('Review changes')
    expect(TRY_SOURCE).toContain('discardStagedOptimization')
    expect(TRY_SOURCE).toContain('applyStagedOptimization')
    expect(TRY_SOURCE).toContain('<ChangeReviewModal')
    expect(TRY_SOURCE).toContain('changeReasons={stream.changesMade?.map')
    expect(TRY_SOURCE).toContain('onApply={applyStagedOptimization}')
    expect(CHANGE_REVIEW_SOURCE).toContain('const applied = await onApply(res.latex)')
    expect(CHANGE_REVIEW_SOURCE).toContain('if (applied === false) return')
  })

  test('trial cancellation no longer restores a stale pre-run snapshot', () => {
    const cancelHandler = TRY_SOURCE.slice(
      TRY_SOURCE.indexOf('const handleCancel'),
      TRY_SOURCE.indexOf('const handleDownload')
    )
    expect(cancelHandler).not.toContain('setValue(preRunSnapshotRef.current)')
    expect(cancelHandler).not.toContain('setLatexContent(preRunSnapshotRef.current)')
  })

  test('workspace records optimization only inside the explicit apply path', () => {
    expect(WORKSPACE_SOURCE).toContain('setStagedAiLatex(aiStream.streamingLatex)')
    expect(WORKSPACE_SOURCE).toContain('Apply optimization')
    const applyHandler = WORKSPACE_SOURCE.slice(
      WORKSPACE_SOURCE.indexOf('const applyOptimizationCandidate'),
      WORKSPACE_SOURCE.indexOf('// Version history: restore from checkpoint')
    )
    expect(applyHandler).toContain('apiClient.recordOptimization')
    expect(WORKSPACE_SOURCE.slice(0, WORKSPACE_SOURCE.indexOf('const applyOptimizationCandidate')))
      .not.toContain('apiClient.recordOptimization')
  })
})
