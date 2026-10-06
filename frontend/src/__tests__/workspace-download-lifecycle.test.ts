import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('workspace PDF download lifecycle', () => {
  it('uses the delayed-revocation download helper in both workspace surfaces', () => {
    const detail = source('../app/workspaces/[workspaceId]/page.tsx')
    const recruiter = source('../app/workspaces/[workspaceId]/recruiter/page.tsx')

    expect(detail).toContain("import { downloadBlob } from '@/lib/download'")
    expect(detail).toContain('downloadBlob(blob,')
    expect(detail).not.toContain('URL.revokeObjectURL(url)')
    expect(recruiter).toContain("import { downloadBlob } from '@/lib/download'")
    expect(recruiter).toContain('downloadBlob(blob,')
    expect(recruiter).not.toContain('URL.revokeObjectURL(url)')
  })
})
