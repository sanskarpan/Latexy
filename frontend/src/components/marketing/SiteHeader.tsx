'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { navItems } from '@/components/marketing/site-links'

export default function SiteHeader() {
  const pathname = usePathname()

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-4 sm:px-8">
      <Link href="/" className="flex items-center gap-3 text-white">
        <span className="text-2xl font-medium tracking-tight">Latexy</span>
      </Link>

      <nav className="flex flex-wrap items-center justify-center gap-4 text-base text-zinc-300 sm:gap-7">
        {navItems.map((item) => {
          const active = pathname === item.href
          return (
            <Link
              key={item.href}
              href={item.href}
              className={active ? 'text-white underline underline-offset-8' : 'hover:text-white'}
            >
              {item.label}
            </Link>
          )
        })}
      </nav>

      <div className="flex items-center gap-3 text-sm sm:text-base">
        <Link href="/dashboard" className="text-zinc-200 hover:text-white">
          Log in
        </Link>
        <Link href="/try" className="btn-primary">
          Get Started
        </Link>
      </div>
    </header>
  )
}
