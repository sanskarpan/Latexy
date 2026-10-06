import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  new URL('../app/workspace/[resumeId]/optimize/page.tsx', import.meta.url),
  'utf8',
)

describe('optimization page document structure', () => {
  it('does not nest a main landmark inside the root layout main', () => {
    expect(source).not.toContain('<main className="min-w-0 space-y-6">')
    expect(source).toContain('<div className="min-w-0 space-y-6">')
  })
})
