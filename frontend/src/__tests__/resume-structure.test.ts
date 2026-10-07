import { describe, expect, it } from 'vitest'
import { moveResumeSibling } from '@/lib/resume-structure'
import { cloneStructuredResume, deriveBuilderPreview } from '@/lib/resume-builder'

describe('stable resume structure permutation', () => {
  it('moves a visible section around hidden slots without dropping their IDs', () => {
    const before = ['summary', 'experience', 'education', 'skills', 'projects']
    const after = moveResumeSibling(before, 'experience', 1, ['experience', 'skills'])
    expect(after).toEqual(['summary', 'education', 'skills', 'experience', 'projects'])
    expect(new Set(after)).toEqual(new Set(before))
    expect(before).toEqual(['summary', 'experience', 'education', 'skills', 'projects'])
  })
  it('reorders persisted bullet IDs without changing their identity', () => {
    expect(moveResumeSibling(['bullet-a', 'bullet-b', 'bullet-c'], 'bullet-b', -1)).toEqual(['bullet-b', 'bullet-a', 'bullet-c'])
  })
  it('does not propose malformed or incomplete sibling identities', () => {
    expect(moveResumeSibling(['a', 'a'], 'a', 1)).toBeNull()
    expect(moveResumeSibling(['a', 'b'], 'a', 1, ['a', 'foreign'])).toBeNull()
    expect(moveResumeSibling(['a', 'b'], 'foreign', -1)).toBeNull()
  })
  it('does not wrap first and last siblings', () => {
    expect(moveResumeSibling(['a', 'b'], 'a', -1)).toBeNull()
    expect(moveResumeSibling(['a', 'b'], 'b', 1)).toBeNull()
  })
  it('preserves manually edited heading labels through builder cloning and preview', () => {
    const structured = cloneStructuredResume()
    structured.basics.summary = 'A careful professional'
    structured.section_titles = { summary: 'Profile & strengths' }
    const cloned = cloneStructuredResume(structured)
    expect(cloned.section_titles).toEqual({ summary: 'Profile & strengths' })
    expect(cloned.section_titles).not.toBe(structured.section_titles)
    expect(deriveBuilderPreview(cloned, 'professional').sections.find((section) => section.key === 'summary')?.title).toBe('Profile & strengths')
  })
})
