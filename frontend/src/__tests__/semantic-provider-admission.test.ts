import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import Panel from '@/components/SemanticOptimizationPanel'

const state = vi.hoisted(() => ({ current: true, request: {} as Record<string, string>,
  optimize: vi.fn<(...args: unknown[]) => Promise<{ success: boolean; job_id: string }>>(),
}))
vi.mock('react', async (original) => ({ ...await original<typeof import('react')>(),
  useState: (initial: unknown) => [initial, vi.fn()], useRef: (value: unknown) => ({ current: value }), useEffect: vi.fn(),
}))
vi.mock('@/lib/api-client', () => ({ apiClient: { optimizeEngineDocument: state.optimize, getAuthToken: () => 'owner-token' } }))
vi.mock('@/hooks/useEngineProviderChoice', () => ({ useEngineProviderChoice: () => ({
  request: state.request, choice: { provider: state.request.provider ?? 'automatic', model: state.request.provider_model ?? '' },
  options: { default: { ready: true }, providers: [] }, error: null, choose: vi.fn(), retry: vi.fn(),
  accountContext: { authToken: 'owner-token', isCurrent: () => state.current },
}) }))
afterEach(() => { vi.clearAllMocks(); state.current = true })

function panel(request: Record<string, string>, admitted: Promise<{ success: boolean; job_id: string }>) {
  state.request = request; state.optimize.mockImplementation(() => admitted)
  const onStarted = vi.fn()
  const tree = Panel({ resumeId: 'resume', identity: 'owner:resume', currentSourceHash: 'source', disabled: false,
    document: { document_id: 'resume', source_mode: 'managed', source_sha256: 'source', content_revision: 4, structured_version: 1,
      template_id: 'standard', nodes: [], opaque_blocks: [] }, jobDescription: 'A target role', setJobDescription: vi.fn(),
    runId: null, onStarted, onApplied: vi.fn() })
  function findButton(node: unknown): ReactElement<{ onClick: () => void }> | undefined {
    if (Array.isArray(node)) return node.map(findButton).find(Boolean)
    if (!node || typeof node !== 'object' || !('props' in node)) return
    const element = node as ReactElement<{ children?: unknown; onClick: () => void }>
    if (element.type === 'button' && element.props.children === 'Find suggestions') return element
    return findButton(element.props.children)
  }
  return { click: () => findButton(tree)!.props.onClick(), optimize: state.optimize, onStarted }
}

describe('provider choice in the actual semantic review panel', () => {
  it('preserves Automatic omission in the panel admission body', async () => {
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    review.click(); await Promise.resolve()
    expect(review.optimize.mock.calls[0][0]).toBe('resume')
    expect(review.optimize.mock.calls[0][1]).toEqual({
      expected_content_revision: 4, expected_source_sha256: 'source', job_description: 'A target role', effort: 'standard',
    })
    expect(review.optimize.mock.calls[0][2]).toMatchObject({ authToken: 'owner-token', isCurrent: expect.any(Function) })
    expect(review.optimize.mock.calls[0][1]).not.toHaveProperty('provider')
    expect(review.optimize.mock.calls[0][1]).not.toHaveProperty('provider_model')
    expect(review.onStarted).toHaveBeenCalledWith('review')
  })
  it('uses the selected provider/model rather than replacing it with defaults', async () => {
    const review = panel({ provider: 'openrouter', provider_model: 'priced/exact-model' }, Promise.resolve({ success: true, job_id: 'review' }))
    review.click(); await Promise.resolve()
    expect(review.optimize.mock.calls[0][1]).toMatchObject({ provider: 'openrouter', provider_model: 'priced/exact-model' })
  })
  it('does not adopt an admission response after account changes', async () => {
    let resolve!: (value: { success: boolean; job_id: string }) => void
    const review = panel({}, new Promise((done) => { resolve = done }))
    review.click(); state.current = false; resolve({ success: true, job_id: 'previous-account-review' }); await Promise.resolve()
    expect(review.onStarted).not.toHaveBeenCalled()
  })
})
