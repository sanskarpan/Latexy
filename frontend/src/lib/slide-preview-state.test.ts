import { describe, expect, it } from 'vitest'
import {
  createSlidePreviewState,
  getSlidePageCount,
  slidePreviewReducer,
} from './slide-preview-state'

describe('presentation slide preview state', () => {
  it('uses the parsed PDF page count over compile metadata and clamps navigation', () => {
    let state = createSlidePreviewState('/first.pdf')
    state = slidePreviewReducer(state, { type: 'loaded', identity: '/first.pdf', requestId: 0, pageCount: 3 })
    expect(getSlidePageCount(state.pageCount, 8)).toBe(3)

    state = slidePreviewReducer(state, { type: 'navigate', identity: '/first.pdf', requestId: 0, page: 99 })
    expect(state.currentPage).toBe(3)
    state = slidePreviewReducer(state, { type: 'navigate', identity: '/first.pdf', requestId: 0, page: 0 })
    expect(state.currentPage).toBe(1)
  })

  it('uses valid metadata until PDF.js reports the actual count', () => {
    expect(getSlidePageCount(null, 5)).toBe(5)
    expect(getSlidePageCount(null, 0)).toBeNull()
    expect(getSlidePageCount(4, 5)).toBe(4)
  })

  it('shows a retry after load failure and starts a fresh request', () => {
    let state = createSlidePreviewState('/deck.pdf')
    state = slidePreviewReducer(state, { type: 'failed', identity: '/deck.pdf', requestId: 0 })
    expect(state.phase).toBe('error')

    state = slidePreviewReducer(state, { type: 'retry', identity: '/deck.pdf', requestId: 0 })
    expect(state).toMatchObject({ phase: 'loading', requestId: 1, currentPage: 1, pageCount: null })
    state = slidePreviewReducer(state, { type: 'loaded', identity: '/deck.pdf', requestId: 1, pageCount: 6 })
    expect(state).toMatchObject({ phase: 'ready', pageCount: 6 })
  })

  it('ignores a late render error from the page that is no longer selected', () => {
    let state = createSlidePreviewState('/deck.pdf')
    state = slidePreviewReducer(state, { type: 'loaded', identity: '/deck.pdf', requestId: 0, pageCount: 4 })
    state = slidePreviewReducer(state, { type: 'navigate', identity: '/deck.pdf', requestId: 0, page: 2 })
    const afterLateError = slidePreviewReducer(state, {
      type: 'failed', identity: '/deck.pdf', requestId: 0, page: 1,
    })

    expect(afterLateError).toBe(state)
    expect(afterLateError.phase).toBe('ready')
  })

  it('offers retry after the selected PDF page fails to load', () => {
    let state = createSlidePreviewState('/deck.pdf')
    state = slidePreviewReducer(state, { type: 'loaded', identity: '/deck.pdf', requestId: 0, pageCount: 4 })
    state = slidePreviewReducer(state, {
      type: 'failed', identity: '/deck.pdf', requestId: 0, page: 1,
    })
    expect(state.phase).toBe('error')

    state = slidePreviewReducer(state, { type: 'retry', identity: '/deck.pdf', requestId: 0 })
    expect(state).toMatchObject({ phase: 'loading', requestId: 1, currentPage: 1 })
  })

  it('ignores a late page-load failure after navigation', () => {
    let state = createSlidePreviewState('/deck.pdf')
    state = slidePreviewReducer(state, { type: 'loaded', identity: '/deck.pdf', requestId: 0, pageCount: 4 })
    state = slidePreviewReducer(state, { type: 'navigate', identity: '/deck.pdf', requestId: 0, page: 2 })
    const afterLateFailure = slidePreviewReducer(state, {
      type: 'failed', identity: '/deck.pdf', requestId: 0, page: 1,
    })

    expect(afterLateFailure).toBe(state)
    expect(afterLateFailure.phase).toBe('ready')
  })

  it('resets on PDF replacement and ignores callbacks from the previous document', () => {
    const previous = createSlidePreviewState('/old.pdf')
    const replaced = slidePreviewReducer(previous, { type: 'replace', identity: '/new.pdf' })
    const afterLateCallback = slidePreviewReducer(replaced, {
      type: 'loaded', identity: '/old.pdf', requestId: 0, pageCount: 12,
    })

    expect(replaced).toMatchObject({ identity: '/new.pdf', phase: 'loading', currentPage: 1, pageCount: null })
    expect(afterLateCallback).toBe(replaced)
  })
})
