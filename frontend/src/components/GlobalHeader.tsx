'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
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

const fullscreenPatterns = [/^\/try$/, /^\/workspace\/[^/]+\/edit$/, /^\/workspace\/[^/]+\/optimize$/, /^\/workspace\/[^/]+\/cover-letter$/]

export default function GlobalHeader() {
  const pathname = usePathname()
  const { data: session } = useSession()
  const flags = useFeatureFlags()
  const { can } = useEntitlements()
  const [hydrated, setHydrated] = useState(false)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const [isSigningOut, setIsSigningOut] = useState(false)
  const { canInstall, prompt: promptInstall } = usePWAInstall()
  // framer-motion honours the OS "reduce motion" preference (the CSS floor in
  // design-tokens.css can't reach JS/WAAPI-driven transforms).
  const reduceMotion = useReducedMotion()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const mobileRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setHydrated(true)
  }, [])

  // Close the account menu on Escape and return focus to its trigger.
  useEffect(() => {
    if (!isUserMenuOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsUserMenuOpen(false)
        triggerRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isUserMenuOpen])

  // Move focus into the account menu when it opens (menu keyboard pattern).
  useEffect(() => {
    if (!isUserMenuOpen) return
    const id = requestAnimationFrame(() => {
      menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
    })
    return () => cancelAnimationFrame(id)
  }, [isUserMenuOpen])

  // Close both menus on navigation (covers link clicks AND browser back/forward).
  useEffect(() => {
    setIsMobileMenuOpen(false)
    setIsUserMenuOpen(false)
  }, [pathname])

  // While the mobile menu is open: lock body scroll, close on Escape, and move
  // focus into the panel so the trap has an anchor.
  useEffect(() => {
    if (!isMobileMenuOpen) return
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsMobileMenuOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    const id = requestAnimationFrame(() => {
      mobileRef.current?.querySelector<HTMLElement>('a[href], button:not([disabled])')?.focus()
    })
    return () => {
      document.body.style.overflow = prevOverflow
      window.removeEventListener('keydown', onKeyDown)
      cancelAnimationFrame(id)
    }
  }, [isMobileMenuOpen])

  // Roving focus + Tab-to-close for the account menu (menu keyboard pattern).
  const handleMenuKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
    )
    if (items.length === 0) return
    const current = items.indexOf(document.activeElement as HTMLElement)
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        items[(current + 1) % items.length]?.focus()
        break
      case 'ArrowUp':
        e.preventDefault()
        items[(current - 1 + items.length) % items.length]?.focus()
        break
      case 'Home':
        e.preventDefault()
        items[0]?.focus()
        break
      case 'End':
        e.preventDefault()
        items[items.length - 1]?.focus()
        break
      case 'Tab':
        setIsUserMenuOpen(false)
        break
    }
  }

  // Cyclic focus trap for the mobile menu panel.
  const handleMobileKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab') return
    const items = Array.from(
      mobileRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])') ?? [],
    )
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

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

  // Match section roots too (e.g. /tracker/123 highlights Tracker), not just
  // exact paths. Fullscreen sub-routes already bail out above.
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/')

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
    if (isSigningOut) return
    setIsSigningOut(true)
    // Clear device-local offline data so the next user on a shared device can't
    // load the previous user's drafts / queued compiles (cross-user leakage).
    try {
      await Promise.all([clearAllDrafts(), clearCompileQueue()])
    } catch {
      // Non-critical — proceed with sign out regardless.
    }
    try {
      await signOut()
    } finally {
      // No `setIsSigningOut(false)` on success — the imminent full-page
      // redirect below makes the button irrelevant, and leaving it disabled
      // avoids a flash back to the enabled state right before navigation.
      window.location.href = '/'
    }
  }

  const menuLink =
    'block rounded-[var(--radius-md)] px-3 py-2 text-sm text-fg-2 transition hover:bg-surface-2 hover:text-fg'

  return (
    <header className="sticky top-0 z-[var(--z-sticky)] border-b border-line bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between px-4 sm:px-6 lg:px-10">
        <Link
          href={isAuthenticated ? '/dashboard' : '/'}
          className="font-display text-xl font-semibold tracking-tight text-fg transition hover:text-accent"
        >
          Latexy
        </Link>

        <nav className="hidden items-center gap-7 md:flex">
          {activeNav.map((item) => {
            const active = isActive(item.href)
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={`font-ui text-sm transition ${
                  active
                    ? 'font-semibold text-accent-strong underline decoration-accent decoration-2 underline-offset-[7px]'
                    : 'font-medium text-fg-2 hover:text-fg'
                }`}
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
                ref={triggerRef}
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
                      ref={menuRef}
                      initial={reduceMotion ? false : { opacity: 0, y: 8, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.98 }}
                      onKeyDown={handleMenuKeyDown}
                      role="menu"
                      aria-label="Account menu"
                      className="absolute right-0 z-[var(--z-dropdown)] mt-2 w-56 rounded-[var(--radius-lg)] border border-line bg-surface p-2 shadow-[var(--shadow-2)]"
                    >
                      <div className="px-3 py-2">
                        <p className="font-ui text-[10px] uppercase tracking-[0.2em] text-fg-3">Account</p>
                        <p className="mt-1 truncate text-sm font-semibold text-fg">{resolvedUser?.email || 'Unknown account'}</p>
                      </div>
                      <div className="my-1 h-px bg-line" />
                      <Link href="/dashboard" role="menuitem" tabIndex={-1} className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Dashboard</Link>
                      {flags.billing && (
                        <Link href="/billing" role="menuitem" tabIndex={-1} className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Billing</Link>
                      )}
                      <Link href="/developer" role="menuitem" tabIndex={-1} className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Developer API</Link>
                      <Link href="/byok" role="menuitem" tabIndex={-1} className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Settings</Link>
                      {isAdmin && (
                        <Link href="/admin" role="menuitem" tabIndex={-1} className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Admin</Link>
                      )}
                      <div className="my-1 h-px bg-line" />
                      <button
                        role="menuitem"
                        tabIndex={-1}
                        onClick={handleSignOut}
                        disabled={isSigningOut}
                        aria-busy={isSigningOut}
                        className="flex w-full items-center gap-2 rounded-[var(--radius-md)] px-3 py-2 text-left text-sm text-err transition hover:bg-[color-mix(in_srgb,var(--err)_12%,transparent)] disabled:cursor-wait disabled:opacity-70"
                      >
                        {isSigningOut && (
                          <span
                            aria-hidden
                            className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-err/30 border-t-err motion-reduce:animate-none"
                          />
                        )}
                        {isSigningOut ? 'Signing out…' : 'Sign Out'}
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
            ref={mobileRef}
            initial={reduceMotion ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, height: 0 }}
            onKeyDown={handleMobileKeyDown}
            className="border-t border-line bg-surface md:hidden"
          >
            <div className="space-y-1 p-4">
              {activeNav.map((item) => {
                const active = isActive(item.href)
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    className={`block rounded-[var(--radius-md)] px-4 py-2.5 font-ui text-sm transition ${
                      active
                        ? 'bg-surface-2 font-semibold text-accent-strong'
                        : 'font-medium text-fg-2 hover:bg-surface-2 hover:text-fg'
                    }`}
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    {item.label}
                  </Link>
                )
              })}

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
