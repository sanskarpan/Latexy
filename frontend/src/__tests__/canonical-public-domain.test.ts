import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (relativePath: string) =>
  fs.readFileSync(path.join(process.cwd(), relativePath), 'utf8')

describe('canonical public domain', () => {
  it('uses the live origin on public share and portfolio pages', () => {
    for (const file of ['src/app/r/[token]/page.tsx', 'src/app/u/[username]/page.tsx']) {
      const source = read(file)
      expect(source, file).toContain('latexy.xyz')
      expect(source, file).not.toContain('latexy.io')
    }
  })
})
