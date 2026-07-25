'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'
import { Download } from 'lucide-react'
import { signOut, useSession } from '@/lib/auth-client'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import { usePWAInstall } from '@/hooks/usePWAInstall'
import { clearAllDrafts } from '@/lib/offline-drafts'
import { clearCompileQueue } from '@/lib/compile-queue'

const guestNav = [
  { label: 'Platform', href: '/platform' },
  { label: 'Templates', href: '/templates' },
  { label: 'Pricing', href: '/billing' },
  { label: 'Resources', href: '/resources' },
  { label: 'FAQ', href: '/faq' },
]

// `feature` (optional) gates a nav item behind an entitlement key. Core
// entry points (Dashboard, Workspace, Studio) are intentionally ungated.
const appNav: Array<{ label: string; href: string; feature?: string }> = [
  { label: 'Dashboard', href: '/dashboard' },
  { label: 'Workspace', href: '/workspace' },
  { label: 'Tracker', href: '/tracker', feature: 'application_tracker' },
  { label: 'Templates', href: '/templates', feature: 'templates' },
  { label: 'Studio', href: '/try' },
]

const fullscreenPatterns = [/^\/workspace\/[^/]+\/edit$/, /^\/workspace\/[^/]+\/optimize$/, /^\/workspace\/[^/]+\/cover-letter$/]

export default function GlobalHeader() {
  const pathname = usePathname()
  const { data: session } = useSession()
  const flags = useFeatureFlags()
  const { can } = useEntitlements()
  const [hydrated, setHydrated] = useState(false)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const { canInstall, prompt: promptInstall } = usePWAInstall()

  useEffect(() => {
    setHydrated(true)
  }, [])

  // Close the account menu on Escape for keyboard accessibility.
  useEffect(() => {
    if (!isUserMenuOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsUserMenuOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isUserMenuOpen])

  if (fullscreenPatterns.some((pattern) => pattern.test(pathname))) {
    return null
  }

  const resolvedSession = hydrated ? session : null
  const resolvedUser = resolvedSession?.user ?? null
  const isAuthenticated = Boolean(resolvedUser)
  const effectiveGuestNav = flags.billing
    ? guestNav
    : guestNav.filter((item) => item.href !== '/billing')
  // Gate feature-specific app nav items behind entitlements (fail-open via
  // can()). Core items without a `feature` key always show.
  const effectiveAppNav = appNav.filter((item) => !item.feature || can(item.feature))
  const activeNav = isAuthenticated ? effectiveAppNav : effectiveGuestNav
  const firstName = resolvedUser?.name?.trim().split(' ')[0] || 'Account'

  // Admin is gated server-side by ADMIN_EMAIL; only surface the link to the
  // configured admin address(es) so it is not advertised to every user.
  const adminEmails = (process.env.NEXT_PUBLIC_ADMIN_EMAIL ?? '')
    .split(',')
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean)
  const isAdmin = Boolean(
    resolvedUser?.email && adminEmails.includes(resolvedUser.email.toLowerCase()),
  )

  const handleSignOut = async () => {
    // Clear device-local offline data so the next user on a shared device can't
    // load the previous user's drafts / queued compiles (cross-user leakage).
    try {
      await Promise.all([clearAllDrafts(), clearCompileQueue()])
    } catch {
      // Non-critical — proceed with sign out regardless.
    }
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
          {hydrated && canInstall && (
            <button
              onClick={promptInstall}
              title="Add Latexy to Home Screen"
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-zinc-400 transition hover:border-white/20 hover:text-white"
            >
              <Download size={12} />
              Install
            </button>
          )}
          {isAuthenticated ? (
            <div className="relative">
              <button
                onClick={() => setIsUserMenuOpen((open) => !open)}
                aria-label={isUserMenuOpen ? 'Close account menu' : 'Open account menu'}
                aria-expanded={isUserMenuOpen}
                aria-haspopup="menu"
                className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 py-1 pl-1 pr-3 text-xs font-semibold text-zinc-300 transition hover:bg-white/10 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-300/60"
              >
                <span
                  aria-hidden
                  className="flex h-6 w-6 items-center justify-center rounded-full bg-orange-300 text-[11px] font-bold text-slate-950"
                >
                  {firstName.charAt(0).toUpperCase()}
                </span>
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
                      role="menu"
                      aria-label="Account menu"
                      className="absolute right-0 z-20 mt-2 w-56 rounded-xl border border-white/10 bg-zinc-900 p-2 shadow-2xl"
                    >
                      <div className="px-3 py-2">
                        <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Account</p>
                        <p className="mt-1 truncate text-sm font-semibold text-white">{resolvedUser?.email || 'Unknown account'}</p>
                      </div>
                      <div className="my-1 h-px bg-white/10" />
                      <Link
                        href="/dashboard"
                        className="block rounded-lg px-3 py-2 text-sm text-zinc-300 transition hover:bg-white/5 hover:text-white"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        Dashboard
                      </Link>
                      {flags.billing && (
                        <Link
                          href="/billing"
                          className="block rounded-lg px-3 py-2 text-sm text-zinc-300 transition hover:bg-white/5 hover:text-white"
                          onClick={() => setIsUserMenuOpen(false)}
                        >
                          Billing
                        </Link>
                      )}
                      <Link
                        href="/developer"
                        className="block rounded-lg px-3 py-2 text-sm text-zinc-300 transition hover:bg-white/5 hover:text-white"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        Developer API
                      </Link>
                      <Link
                        href="/byok"
                        className="block rounded-lg px-3 py-2 text-sm text-zinc-300 transition hover:bg-white/5 hover:text-white"
                        onClick={() => setIsUserMenuOpen(false)}
                      >
                        Settings
                      </Link>
                      {isAdmin && (
                        <Link
                          href="/admin"
                          className="block rounded-lg px-3 py-2 text-sm text-zinc-300 transition hover:bg-white/5 hover:text-white"
                          onClick={() => setIsUserMenuOpen(false)}
                        >
                          Admin
                        </Link>
                      )}
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

              {!isAuthenticated && (
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
