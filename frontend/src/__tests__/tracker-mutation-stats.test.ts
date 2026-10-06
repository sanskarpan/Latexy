import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const TRACKER_SOURCE = readFileSync(
  new URL('../app/tracker/page.tsx', import.meta.url),
  'utf8',
)

describe('tracker mutation and stats consistency', () => {
  it('does not classify a secondary stats outage as a mutation failure', () => {
    expect(TRACKER_SOURCE).not.toContain('setStats(await apiClient.getTrackerStats())')
    expect(TRACKER_SOURCE).not.toContain('getTrackerStats().then(setStats).catch(() => {})')
    expect(TRACKER_SOURCE).not.toContain('apiClient.getTrackerStats()')
  })

  it('recomputes stats with optimistic board mutations', () => {
    expect(TRACKER_SOURCE).toContain('const boardReadyForCurrentOwner = boardIdentityAccepted?.ownerId === trackerOwnerId')
    expect(TRACKER_SOURCE).toContain('const visibleBoardData = boardReadyForCurrentOwner ? boardData : createEmptyBoard()')
    expect(TRACKER_SOURCE).toContain('acceptedBoardIdentityRef.current = { ownerId, generation }')
    expect(TRACKER_SOURCE).toContain('const visibleStaleApps = staleReadyForCurrentOwner ? staleApps : []')
    expect(TRACKER_SOURCE).not.toContain('>{staleApps.length}</span>')
    expect(TRACKER_SOURCE).toContain('const stats = useMemo(() => computeStatsFromBoard(visibleBoardData), [visibleBoardData])')
    expect(TRACKER_SOURCE).not.toContain('computeStatsFromBoard(boardData)')
    expect(TRACKER_SOURCE).toContain('const handleAppCreated')
    expect(TRACKER_SOURCE).toContain('newBoard[updated.status]')
  })

  it('rolls back only the current card for an owned mutation failure', () => {
    expect(TRACKER_SOURCE).not.toContain('setBoardData(boardData)')
    expect(TRACKER_SOURCE).toContain('statusMutationRef')
    expect(TRACKER_SOURCE).toContain('statusMutationRef.current[id] !== mutationToken')
    expect(TRACKER_SOURCE).not.toContain('statusMutationRef.current = {}')
    expect(TRACKER_SOURCE).toContain('boardOwnerRef.current !== mutationOwnerId')
    expect(TRACKER_SOURCE).toContain('if (!currentApp || currentApp.status !== newStatus) return current')
    expect(TRACKER_SOURCE).toContain('Object.entries(current).map(([column, apps]) => [column, apps.filter((item) => item.id !== id)])')
    expect(TRACKER_SOURCE).toContain('if (boardOwnerRef.current !== deleteOwnerId) return')
    expect(TRACKER_SOURCE).not.toContain('const [stats, setStats]')
  })

  it('restores the pre-drag snapshot when a drag is cancelled or dropped outside', () => {
    expect(TRACKER_SOURCE).toContain('dragSnapshotRef.current = boardData')
    expect(TRACKER_SOURCE).toContain('onDragCancel={restoreCancelledDrag}')
    expect(TRACKER_SOURCE).toContain('if (!over)')
    expect(TRACKER_SOURCE).toContain('restoreCancelledDrag()')
  })
})
