import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const EDITOR = readFileSync(
  new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url),
  'utf8',
)

describe('derived compile history isolation', () => {
  it('does not attach a standalone TikZ preview to the resume', () => {
    const handler = EDITOR.slice(
      EDITOR.indexOf('const handleTikZPreview'),
      EDITOR.indexOf('const runAiOptimize'),
    )
    expect(handler).not.toContain('resume_id: resumeId')
  })
})
