import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('route shells and root main hydration contract', () => {
  it('does not nest native main landmarks under the root layout main', () => {
    const routeSources = [
      '../app/tenant-invite/page.tsx',
      '../app/workspace/variant/[resumeId]/page.tsx',
      '../app/workspace/[resumeId]/cover-letter/page.tsx',
      '../app/workspace/[resumeId]/edit/page.tsx',
      '../app/r/[token]/page.tsx',
    ]

    for (const route of routeSources) {
      expect(source(route), route).not.toMatch(/<main\b|<\/main>/)
    }
  })
})
