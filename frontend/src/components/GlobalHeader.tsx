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
import ModeToggle from '@/components/theme/ModeToggle'

const guestNav = [
  { label: 'Platform', href: '/platform' },
  { label: 'Templates', href: '/templates' },
  { label: 'Pricing', href: '/pricing' },
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
    : guestNav.filter((item) => item.href !== '/pricing')
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

  const menuLink =
    'block rounded-[var(--radius-md)] px-3 py-2 text-sm text-fg-2 transition hover:bg-surface-2 hover:text-fg'

  return (
    <header className="sticky top-0 z-[var(--z-sticky)] border-b border-line bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between px-4 sm:px-6 lg:px-10">
        <Link href="/" className="font-display text-xl font-semibold tracking-tight text-fg transition hover:text-accent">
          Latexy
        </Link>

        <nav className="hidden items-center gap-7 md:flex">
          {activeNav.map((item) => {
            const active = pathname === item.href
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`font-ui text-sm font-medium transition ${active ? 'text-accent-strong' : 'text-fg-2 hover:text-fg'}`}
              >
                {item.label}
              </Link>
            )
          })}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          <ModeToggle />
          {hydrated && canInstall && (
            <button
              onClick={promptInstall}
              title="Add Latexy to Home Screen"
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line px-3 py-1.5 font-ui text-xs font-medium text-fg-2 transition hover:border-line-2 hover:text-fg"
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
                className="flex items-center gap-2 rounded-[var(--radius-pill)] border border-line bg-surface-2 py-1 pl-1 pr-3 font-ui text-xs font-semibold text-fg-2 transition hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
              >
                <span
                  aria-hidden
                  className="flex h-6 w-6 items-center justify-center rounded-[var(--radius-pill)] bg-accent text-[11px] font-bold text-accent-fg"
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
                      className="fixed inset-0 z-[var(--z-raised)]"
                      aria-label="Close account menu"
                    />
                    <motion.div
                      initial={{ opacity: 0, y: 8, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 8, scale: 0.98 }}
                      role="menu"
                      aria-label="Account menu"
                      className="absolute right-0 z-[var(--z-dropdown)] mt-2 w-56 rounded-[var(--radius-lg)] border border-line bg-surface p-2 shadow-[var(--shadow-2)]"
                    >
                      <div className="px-3 py-2">
                        <p className="font-ui text-[10px] uppercase tracking-[0.2em] text-fg-3">Account</p>
                        <p className="mt-1 truncate text-sm font-semibold text-fg">{resolvedUser?.email || 'Unknown account'}</p>
                      </div>
                      <div className="my-1 h-px bg-line" />
                      <Link href="/dashboard" className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Dashboard</Link>
                      {flags.billing && (
                        <Link href="/billing" className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Billing</Link>
                      )}
                      <Link href="/developer" className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Developer API</Link>
                      <Link href="/byok" className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Settings</Link>
                      {isAdmin && (
                        <Link href="/admin" className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Admin</Link>
                      )}
                      <div className="my-1 h-px bg-line" />
                      <button
                        onClick={handleSignOut}
                        className="block w-full rounded-[var(--radius-md)] px-3 py-2 text-left text-sm text-err transition hover:bg-[color-mix(in_srgb,var(--err)_12%,transparent)]"
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
              <Link href="/login" className="font-ui text-sm font-medium text-fg-2 transition hover:text-fg">
                Log In
              </Link>
              <Link
                href="/try"
                className="rounded-[var(--radius-md)] bg-accent px-4 py-1.5 font-ui text-xs font-semibold text-accent-fg transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
              >
                Try Free
              </Link>
            </>
          )}
        </div>

        <div className="flex items-center gap-2 md:hidden">
          <ModeToggle />
          <button
            className="rounded-[var(--radius-md)] border border-line px-3 py-1 font-ui text-xs font-semibold text-fg-2 transition hover:border-line-2 hover:text-fg"
            onClick={() => setIsMobileMenuOpen((open) => !open)}
            aria-label={isMobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
            aria-expanded={isMobileMenuOpen}
          >
            {isMobileMenuOpen ? 'Close' : 'Menu'}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {isMobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="border-t border-line bg-surface md:hidden"
          >
            <div className="space-y-1 p-4">
              {activeNav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="block rounded-[var(--radius-md)] px-4 py-2.5 font-ui text-sm font-medium text-fg-2 transition hover:bg-surface-2 hover:text-fg"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  {item.label}
                </Link>
              ))}

              {!isAuthenticated && (
                <div className="mt-3 grid grid-cols-2 gap-2 border-t border-line pt-3">
                  <Link
                    href="/login"
                    className="rounded-[var(--radius-md)] border border-line py-2.5 text-center font-ui text-sm font-medium text-fg"
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    Log In
                  </Link>
                  <Link
                    href="/try"
                    className="rounded-[var(--radius-md)] bg-accent py-2.5 text-center font-ui text-sm font-semibold text-accent-fg"
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
