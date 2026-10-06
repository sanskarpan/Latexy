import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const workspace = fs.readFileSync(
  path.join(process.cwd(), 'src/app/workspace/page.tsx'),
  'utf8',
)
const publicPortfolio = fs.readFileSync(
  path.join(process.cwd(), 'src/app/u/[username]/page.tsx'),
  'utf8',
)

describe('public portfolio privacy', () => {
  it('offers an explicit per-resume visibility control', () => {
    expect(workspace).toContain('portfolio_visible: !resume.portfolio_visible')
    expect(workspace).toContain('Show on public profile')
    expect(workspace).toContain('Hide from public profile')
  })

  it('provides a screen-reader-friendly text alternative for public resumes', () => {
    expect(publicPortfolio).toContain('Read accessible resume text')
    expect(publicPortfolio).toContain('r.accessible_text')
  })
})
