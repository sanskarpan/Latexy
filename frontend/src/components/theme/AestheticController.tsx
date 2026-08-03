'use client'

import { useEffect } from 'react'
import { usePathname } from 'next/navigation'

/**
 * Sets `data-aesthetic` on the document root from the current route (redesign,
 * PRD 2026-08-03). A pragmatic, low-risk alternative to a route-group file
 * restructure: marketing/public + auth surfaces render **Typeset**; the
 * authenticated app (and the public Studio `/try`, which IS the product editor)
 * render **Compiler**. Mounted once in the root layout.
 */

// Public/marketing + auth surfaces → Typeset. Matched by exact path or prefix.
const TYPESET_EXACT = new Set<string>([
  '/', '/platform', '/pricing', '/templates', '/resources', '/faq', '/updates',
  '/developer', '/login', '/signup', '/forgot-password', '/reset-password', '/verify-email',
])
const TYPESET_PREFIX = ['/u/', '/r/'] // public profile + share links

function aestheticFor(pathname: string): 'typeset' | 'compiler' {
  if (TYPESET_EXACT.has(pathname)) return 'typeset'
  if (TYPESET_PREFIX.some((p) => pathname.startsWith(p))) return 'typeset'
  return 'compiler' // dashboard, workspace, /try, admin, everything authenticated
}

export default function AestheticController() {
  const pathname = usePathname()
  useEffect(() => {
    document.documentElement.setAttribute('data-aesthetic', aestheticFor(pathname || '/'))
  }, [pathname])
  return null
}
