import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

const { mockHeaders } = vi.hoisted(() => ({ mockHeaders: vi.fn() }))

vi.mock('next/headers', () => ({ headers: mockHeaders }))

import Loading from '@/app/loading'

describe('root route loading fallback', () => {
  afterEach(() => mockHeaders.mockReset())

  it('renders the visible updates content for the updates route', async () => {
    mockHeaders.mockResolvedValue(new Headers({ 'x-latexy-route-pathname': '/updates' }))

    const markup = renderToStaticMarkup(await Loading())

    expect(markup).toContain('<h1')
    expect(markup).toContain('Shipping log and')
    expect(markup).toContain('<article')
    expect(markup).not.toContain('Loading page content')
  })

  it('keeps the generic loading indicator on other routes', async () => {
    mockHeaders.mockResolvedValue(new Headers({ 'x-latexy-route-pathname': '/pricing' }))

    const markup = renderToStaticMarkup(await Loading())

    expect(markup).toContain('role="status"')
    expect(markup).toContain('Loading page content')
    expect(markup).not.toContain('Shipping log and')
  })
})
