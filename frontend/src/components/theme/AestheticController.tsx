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
    const root = document.documentElement
    // not-found.tsx sets this flag (via an inline script that runs during the
    // initial HTML parse, before this effect ever fires) because a genuinely
    // unmatched route's real pathname isn't distinguishable from an
    // authenticated "compiler" route by string alone. Honor it, then clear it
    // on a macrotask (not synchronously) so a later real navigation recomputes
    // normally — a sync removal would be undone by React 18 dev StrictMode's
    // double effect-invoke (mount -> cleanup -> mount), which would otherwise
    // see the flag already gone on its second pass and fall through to
    // 'compiler'.
    if (root.hasAttribute('data-force-typeset')) {
      root.setAttribute('data-aesthetic', 'typeset')
      const clear = setTimeout(() => root.removeAttribute('data-force-typeset'), 0)
      return () => clearTimeout(clear)
    }
    root.setAttribute('data-aesthetic', aestheticFor(pathname || '/'))
  }, [pathname])
  return null
}
