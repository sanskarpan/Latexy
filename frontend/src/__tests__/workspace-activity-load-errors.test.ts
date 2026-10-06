import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const WORKSPACE_SOURCE = readFileSync(
  new URL('../app/workspace/page.tsx', import.meta.url),
  'utf8',
).replace(/\r\n/g, '\n')

describe('workspace recent-activity isolation', () => {
  it('loads activity separately from primary résumé data', () => {
    expect(WORKSPACE_SOURCE).toContain('const loadRecentActivity = useCallback')
    expect(WORKSPACE_SOURCE).not.toContain('const [resumesData, jobsData, statsData]')
    expect(WORKSPACE_SOURCE).toContain('void loadRecentActivity()')
  })

  it('shows an accessible retry state instead of false empty activity', () => {
    expect(WORKSPACE_SOURCE).toContain('Recent activity could not be loaded.')
    expect(WORKSPACE_SOURCE).toContain('role="alert"')
    expect(WORKSPACE_SOURCE).toContain('Retry activity')
  })

  it('routes post-tailor refresh through the primary recoverable loader', () => {
    expect(WORKSPACE_SOURCE).not.toContain('apiClient.listAllResumes().then((data)')
    expect(WORKSPACE_SOURCE).toContain('// Refresh resume list so the new fork appears\n            void fetchData()')
  })

  it('keeps a run-detail outage distinct from a genuine missing result', () => {
    expect(WORKSPACE_SOURCE).toContain('const [jobResultErrors, setJobResultErrors]')
    expect(WORKSPACE_SOURCE).not.toContain('setJobResultCache(prev => ({ ...prev, [jobId]: null }))')
    expect(WORKSPACE_SOURCE).toContain('Run details could not be loaded.')
    expect(WORKSPACE_SOURCE).toContain('Retry details')
  })
})
