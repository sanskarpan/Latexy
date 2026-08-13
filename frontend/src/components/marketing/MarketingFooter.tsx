'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

export default function MarketingFooter() {
  const pathname = usePathname()
  // The marketing footer belongs only on public/marketing + auth surfaces.
  // App surfaces (the authenticated product) must never show it.
  const APP_PREFIXES = [
    '/try', '/dashboard', '/workspace', '/workspaces', '/billing',
    '/byok', '/settings', '/admin', '/tracker',
  ]
  const hidden = APP_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'))
  if (hidden) return null

  const year = new Date().getFullYear()

  return (
    <footer className="mt-10 border-t border-line bg-surface-2">
      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="font-display text-lg font-semibold text-fg">Latexy</p>
            <p className="mt-0.5 font-body text-sm text-fg-2">Résumés, typeset — precision for modern applicants.</p>
          </div>
          <nav className="flex flex-wrap items-center gap-5 font-ui text-sm text-fg-2">
            <Link href="/platform" className="transition hover:text-fg">Platform</Link>
            <Link href="/resources" className="transition hover:text-fg">Resources</Link>
            <Link href="/updates" className="transition hover:text-fg">Updates</Link>
            <Link href="/faq" className="transition hover:text-fg">FAQ</Link>
            <Link
              href="/try"
              className="rounded-[var(--radius-md)] bg-accent px-4 py-1.5 font-semibold text-accent-fg transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
            >
              Open Studio
            </Link>
          </nav>
        </div>

        <div className="mt-8 flex flex-col gap-4 border-t border-line pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="font-body text-xs text-fg-3">© {year} Latexy. All rights reserved.</p>
        </div>
      </div>
    </footer>
  )
}
