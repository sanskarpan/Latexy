'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

export default function MarketingFooter() {
  const pathname = usePathname()
  const hidden = /^\/workspace\/[^/]+\/(edit|optimize)$/.test(pathname)
  if (hidden) return null

  return (
    <footer className="mt-10 border-t border-line bg-surface-2">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-8 sm:px-8">
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
    </footer>
  )
}
