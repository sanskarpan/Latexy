'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

export default function MarketingFooter() {
  const pathname = usePathname()
  const hidden = /^\/workspace\/[^/]+\/(edit|optimize)$/.test(pathname)
  if (hidden) return null

  return (
    <footer className="mt-6 surface-panel edge-highlight px-5 py-6 sm:px-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-lg font-semibold text-white">Latexy</p>
          <p className="text-sm text-zinc-400">Precision resume intelligence for modern applicants.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm text-zinc-300">
          <Link href="/platform" className="hover:text-white">Platform</Link>
          <Link href="/resources" className="hover:text-white">Resources</Link>
          <Link href="/updates" className="hover:text-white">Updates</Link>
          <Link href="/faq" className="hover:text-white">FAQ</Link>
          <Link href="/try" className="btn-accent">Open Studio</Link>
        </div>
      </div>
    </footer>
  )
}
