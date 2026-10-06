import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('Monaco E2E interaction contract', () => {
  it('uses the test hook for editor setup instead of view-line geometry', () => {
    const specs = [
      '../../e2e/ats-quick-score.spec.ts',
      '../../e2e/macros.spec.ts',
      '../../e2e/phrase-library.spec.ts',
    ].map((path) => source(path))

    for (const spec of specs) expect(spec).not.toContain('.view-lines')
    expect(specs[0]).toContain('__latexyMonacoEditor')
    expect(specs[1]).toContain('setPosition')
    expect(specs[2]).toContain('setPosition')
  })
})
