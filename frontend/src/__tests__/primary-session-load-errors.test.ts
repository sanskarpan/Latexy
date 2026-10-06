import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('primary authenticated routes', () => {
  it.each([
    ['dashboard', '../app/dashboard/page.tsx', 'Dashboard', 'sessionError && !session'],
    ['personal workspace', '../app/workspace/page.tsx', 'Workspace', 'sessionError && !session'],
    ['application tracker', '../app/tracker/page.tsx', 'Application tracker', 'sessionError && !session'],
    ['team workspaces', '../app/workspaces/page.tsx', 'Team workspaces', 'sessionError && !session'],
    ['team workspace detail', '../app/workspaces/[workspaceId]/page.tsx', 'Team workspace', 'sessionError && !session'],
    ['recruiter dashboard', '../app/workspaces/[workspaceId]/recruiter/page.tsx', 'Recruiter dashboard', 'sessionError && !session'],
    ['cover letter library', '../app/workspace/cover-letters/page.tsx', 'Cover letter library', 'sessionError && !session'],
    ['resume merge', '../app/workspace/merge/page.tsx', 'Resume merge', 'sessionError && !session'],
    ['career path', '../app/workspace/[resumeId]/career/page.tsx', 'Career path', 'sessionError && !session'],
    ['batch tailoring', '../app/workspace/[resumeId]/batch-tailor/page.tsx', 'Batch tailoring', 'sessionError && !session'],
    ['optimization', '../app/workspace/[resumeId]/optimize/page.tsx', 'Optimization workspace', 'sessionError && !session'],
    ['cover-letter workflow', '../app/workspace/[resumeId]/cover-letter/page.tsx', 'Cover-letter workspace', 'sessionError && !session'],
    ['new resume', '../app/workspace/new/page.tsx', 'New resume', 'sessionError && !session'],
    ['resume editor', '../app/workspace/[resumeId]/edit/page.tsx', 'Resume editor', 'sessionError && !sessionData'],
    ['tenant management', '../app/admin/tenant/page.tsx', 'Tenant management', 'sessionError && !session'],
  ])('%s distinguishes session lookup failure from signed out', (_name, path, area, errorGuard) => {
    const route = source(path)
    expect(route).toContain('error: sessionError')
    expect(route).toContain(errorGuard)
    expect(route).toContain(`<SessionLoadError area="${area}" />`)
  })

  it('offers an accessible retry without treating the failure as logout', () => {
    const component = source('../components/SessionLoadError.tsx')
    expect(component).toContain('role="alert"')
    expect(component).toContain('window.location.reload()')
    expect(component).toContain('could not verify your session')
  })
})
