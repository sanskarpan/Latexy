import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const NEXT_CONFIG = readFileSync(
  fileURLToPath(new URL('../../next.config.js', import.meta.url)),
  'utf8',
)

describe('Monaco server bundle resolution', () => {
  it('pins bare Monaco runtime imports to the ESM editor API entry', () => {
    expect(NEXT_CONFIG).toContain("config.resolve.alias['monaco-editor$']")
    expect(NEXT_CONFIG).toContain("require.resolve('monaco-editor/esm/vs/editor/editor.api.js')")
  })
})
