import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { readFileSync } = vi.hoisted(() => ({ readFileSync: vi.fn() }))

vi.mock('node:fs', () => ({
  default: { readFileSync },
  readFileSync,
}))

import LegalDoc from '@/components/marketing/LegalDoc'

describe('LegalDoc markdown renderer', () => {
  beforeEach(() => {
    readFileSync.mockReturnValue([
      '# Privacy Policy',
      '',
      '## How we use information',
      '',
      '- provide **authentication**, document editing, compilation, sharing, AI,',
      '  collaboration, integrations, billing, and support;',
      '- enforce plan limits;',
      '',
      'This paragraph follows the list.',
      '',
      '## More details',
      '',
      'Read the [privacy policy](https://latexy.xyz/privacy) for details.',
    ].join('\r\n'))
  })

  it('keeps wrapped list text in the same item and renders following content structurally', () => {
    const html = renderToStaticMarkup(createElement(LegalDoc, { file: 'privacy-policy' }))

    expect(html).toContain('<h1')
    expect(html).toContain('<h2')
    expect(html).toContain('<strong class="font-semibold text-fg">authentication</strong>')
    expect(html).toContain('<a href="https://latexy.xyz/privacy"')
    expect(html).toContain('AI, collaboration, integrations, billing, and support;')
    expect(html.match(/<ul/g)).toHaveLength(1)
    expect(html.match(/<li/g)).toHaveLength(2)
    expect(html).toContain('</ul><p class="mt-4 leading-relaxed text-fg-2">This paragraph follows the list.</p>')
    expect(html).not.toContain('</li></ul><p class="mt-4 leading-relaxed text-fg-2">collaboration')
    expect(html).not.toContain('\r')
  })
})
