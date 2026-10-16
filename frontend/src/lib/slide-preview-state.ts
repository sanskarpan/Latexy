export type SlidePreviewPhase = 'loading' | 'ready' | 'error'

export interface SlidePreviewState {
  identity: string
  requestId: number
  phase: SlidePreviewPhase
  currentPage: number
  pageCount: number | null
}

export type SlidePreviewAction =
  | { type: 'replace'; identity: string }
  | { type: 'loaded'; identity: string; requestId: number; pageCount: number }
  | { type: 'failed'; identity: string; requestId: number; page?: number }
  | { type: 'retry'; identity: string; requestId: number }
  | { type: 'navigate'; identity: string; requestId: number; page: number }

export function createSlidePreviewState(identity: string): SlidePreviewState {
  return { identity, requestId: 0, phase: 'loading', currentPage: 1, pageCount: null }
}

export function getSlidePageCount(actual: number | null, metadata: number | null | undefined): number | null {
  if (actual !== null && Number.isInteger(actual) && actual > 0) return actual
  return metadata !== null && metadata !== undefined && Number.isInteger(metadata) && metadata > 0
    ? metadata
    : null
}

export function slidePreviewReducer(state: SlidePreviewState, action: SlidePreviewAction): SlidePreviewState {
  if (action.type === 'replace') return createSlidePreviewState(action.identity)
  if (action.identity !== state.identity || action.requestId !== state.requestId) return state

  switch (action.type) {
    case 'loaded': {
      if (!Number.isInteger(action.pageCount) || action.pageCount < 1) {
        return { ...state, phase: 'error' }
      }
      return {
        ...state,
        phase: 'ready',
        pageCount: action.pageCount,
        currentPage: Math.min(state.currentPage, action.pageCount),
      }
    }
    case 'failed':
      if (action.page !== undefined && action.page !== state.currentPage) return state
      return { ...state, phase: 'error' }
    case 'retry':
      return { ...state, requestId: state.requestId + 1, phase: 'loading', currentPage: 1, pageCount: null }
    case 'navigate': {
      const maximum = state.pageCount ?? Number.POSITIVE_INFINITY
      return { ...state, currentPage: Math.max(1, Math.min(maximum, Math.floor(action.page))) }
    }
  }
}
