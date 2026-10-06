import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const recruiterSource = readFileSync(
  new URL('../app/workspaces/[workspaceId]/recruiter/page.tsx', import.meta.url),
  'utf8',
)
const tenantSource = readFileSync(
  new URL('../app/admin/tenant/page.tsx', import.meta.url),
  'utf8',
)

describe('workspace resume activity semantics', () => {
  it('never renders legacy milestones as unqualified reviewer activity', () => {
    expect(recruiterSource).toContain('candidate viewed their submission')
    expect(recruiterSource).toContain('candidate downloaded their PDF')
    expect(recruiterSource).toContain("resume.opened_actor === 'candidate'")
    expect(recruiterSource).toContain("resume.opened_source === 'candidate_self'")
    expect(recruiterSource).toContain("resume.downloaded_actor === 'candidate'")
    expect(recruiterSource).toContain("resume.downloaded_source === 'candidate_self'")
    expect(recruiterSource).not.toContain("? ' · opened'")
    expect(recruiterSource).not.toContain("? ' · downloaded'")
  })

  it('labels cohort milestones as candidate activity', () => {
    expect(tenantSource).toContain('Candidate opened')
    expect(tenantSource).toContain('Candidate downloaded')
    expect(tenantSource).toContain("submission.opened_source === 'candidate_self'")
    expect(tenantSource).toContain("submission.downloaded_source === 'candidate_self'")
  })
})
