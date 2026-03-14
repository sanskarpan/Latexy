'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'
import { signOut, useSession } from '@/lib/auth-client'

const guestNav = [
  { label: 'Platform', href: '/platform' },
  { label: 'Templates', href: '/templates' },
  { label: 'Pricing', href: '/billing' },
  { label: 'Resources', href: '/resources' },
  { label: 'FAQ', href: '/faq' },
]

const appNav = [
  { label: 'Dashboard', href: '/dashboard' },
  { label: 'Workspace', href: '/workspace' },
  { label: 'Templates', href: '/templates' },
  { label: 'Studio', href: '/try' },
]

const fullscreenPatterns = [/^\/workspace\/[^/]+\/edit$/, /^\/workspace\/[^/]+\/optimize$/, /^\/workspace\/[^/]+\/cover-letter$/]

export default function GlobalHeader() {
  const pathname = usePathname()
  const { data: session } = useSession()
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)

  if (fullscreenPatterns.some((pattern) => pattern.test(pathname))) {
    return null
  }

  const activeNav = session ? appNav : guestNav
  const firstName = session?.user.name?.trim().split(' ')[0] || 'Account'

  const handleSignOut = async () => {
    await signOut()
    window.location.href = '/'
  }

  return (
    <header className="sticky top-0 z-50 border-b border-white/10 bg-black/65 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between px-4 sm:px-6 lg:px-10">
        <Link href="/" className="text-xl font-semibold tracking-tight text-white transition hover:text-orange-100">
          Latexy
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {activeNav.map((item) => {
            const active = pathname === item.href
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`text-sm font-medium transition ${active ? 'text-orange-200' : 'text-zinc-400 hover:text-white'}`}
              >
                {item.label}
              </Link>
            )
          })}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          {session ? (
            <div className="relative">
              <button
                onClick={() => setIsUserMenuOpen((open) => !open)}
                aria-label={isUserMenuOpen ? 'Close account menu' : 'Open account menu'}
                aria-expanded={isUserMenuOpen}
                className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:bg-white/10 hover:text-white"
              >
                {firstName}
              </button>

              <AnimatePresence>
                {isUserMenuOpen && (
                  <>
                    <button
                      type="button"
                      onClick={() => setIsUserMenuOpen(false)}
                      className="fixed inset-0 z-10"
                      aria-label="Close account menu"
                    />
                    <motion.div
                      initial={{ opacity: 0, y: 8, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 8, scale: 0.98 }}
                      className="absolute right-0 z-20 mt-2 w-56 rounded-xl border border-white/10 bg-zinc-900 p-2 shadow-2xl"
                    >
                      <div className="px-3 py-2">
                        <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Account</p>
                        <p className="mt-1 truncate text-sm font-semibold text-white">{session.user.email}</p>
                      </div>
                      <div className="my-1 h-px bg-white/10" />
                      <Link
                        href="/dashboard"
                        className="block rounded-lg px-3 py-2 text-sm text-zinc-300 transition hover:bg-white/5 hover:text-white"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        Dashboard
                      </Link>
                      <Link
                        href="/billing"
                        className="block rounded-lg px-3 py-2 text-sm text-zinc-300 transition hover:bg-white/5 hover:text-white"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        Billing
                      </Link>
                      <Link
                        href="/byok"
                        className="block rounded-lg px-3 py-2 text-sm text-zinc-300 transition hover:bg-white/5 hover:text-white"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        Settings
                      </Link>
                      <div className="my-1 h-px bg-white/10" />
                      <button
                        onClick={handleSignOut}
                        className="block w-full rounded-lg px-3 py-2 text-left text-sm text-rose-300 transition hover:bg-rose-500/10"
                      >
                        Sign Out
                      </button>
                    </motion.div>
                  </>
                )}
              </AnimatePresence>
            </div>
          ) : (
            <>
              <Link href="/login" className="text-sm font-medium text-zinc-400 transition hover:text-white">
                Log In
              </Link>
              <Link href="/try" className="btn-accent px-4 py-1.5 text-xs">
                Try Free
              </Link>
            </>
          )}
        </div>

        <button
          className="rounded-lg border border-white/10 px-3 py-1 text-xs font-semibold text-zinc-300 transition hover:border-white/20 hover:text-white md:hidden"
          onClick={() => setIsMobileMenuOpen((open) => !open)}
          aria-label={isMobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
          aria-expanded={isMobileMenuOpen}
        >
          {isMobileMenuOpen ? 'Close' : 'Menu'}
        </button>
      </div>

      <AnimatePresence>
        {isMobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="border-t border-white/10 bg-zinc-950 md:hidden"
          >
            <div className="space-y-1 p-4">
              {activeNav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="block rounded-lg px-4 py-2 text-sm font-medium text-zinc-300 transition hover:bg-white/5 hover:text-white"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  {item.label}
                </Link>
              ))}

              {!session && (
                <div className="mt-3 grid grid-cols-2 gap-2 border-t border-white/10 pt-3">
                  <Link
                    href="/login"
                    className="rounded-lg border border-white/10 py-2 text-center text-sm font-medium text-white"
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    Log In
                  </Link>
                  <Link
                    href="/try"
                    className="rounded-lg bg-orange-300 py-2 text-center text-sm font-semibold text-slate-950"
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    Try Free
                  </Link>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  )
}
