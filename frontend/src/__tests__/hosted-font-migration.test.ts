import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const panel = fs.readFileSync(
  path.join(process.cwd(), 'src/components/DesignPanel.tsx'),
  'utf8',
)

describe('hosted font migration', () => {
  it('disables missing fonts and explains how an existing document can recover', () => {
    expect(panel).toContain('disabled={!available}')
    expect(panel).toContain('Unavailable in the hosted compiler')
    expect(panel).toContain('to replace it before compiling')
  })
})
