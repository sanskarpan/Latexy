import { describe, expect, test } from 'vitest'

import { canEditResume, type ResumeAccessRole } from '@/lib/resume-access'

describe('resume collaborator access', () => {
    test.each<ResumeAccessRole>(['owner', 'editor'])('%s can persist document edits', role => {
        expect(canEditResume(role)).toBe(true)
    })

    test.each<ResumeAccessRole>(['commenter', 'viewer'])('%s remains read-only', role => {
        expect(canEditResume(role)).toBe(false)
    })
})
