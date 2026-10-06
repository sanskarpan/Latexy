import { describe, expect, it } from 'vitest'
import { initialState, jobStreamReducer } from '@/hooks/useJobStream.reducer'
import type { SemanticReadyEvent } from '@/lib/event-types'
const ready: SemanticReadyEvent = { event_id: 'patch-1', sequence: 1, timestamp: 1, type: 'patch.ready', job_id: 'job',
  run_id: 'job', document_id: 'document', content_revision: 3, source_sha256: 'source', branch: 'candidate', provisional: true,
  patch: { patch_id: 'one', node_id: 'node', expected_node_revision: 'revision', original_text: 'Built tools', text: 'Developed tools', reason: 'Clarity' } }

describe('provisional semantic review', () => {
  it('deduplicates early cards and removes candidates rejected by final checks', () => {
    let state = jobStreamReducer({ ...initialState, status: 'processing' }, ready)
    state = jobStreamReducer(state, ready)
    expect(state.semanticPatches).toHaveLength(1)
    state = jobStreamReducer(state, { ...ready, type: 'review.ready', patch: undefined, final_patch_ids: [], provisional: false })
    expect(state.semanticPatches).toEqual([])
    expect(jobStreamReducer(state, ready).semanticPatches).toEqual([])
    expect(state.status).toBe('processing')
  })
  it('does not mix revisions or resurrect cancelled suggestions', () => {
    const state = jobStreamReducer({ ...initialState, status: 'processing' }, ready)
    expect(jobStreamReducer(state, { ...ready, source_sha256: 'newer', patch: { ...ready.patch!, patch_id: 'two' } }).semanticPatches).toHaveLength(1)
    expect(jobStreamReducer({ ...initialState, status: 'cancelled' }, ready).semanticPatches).toEqual([])
  })
})
