import Link from 'next/link'

/**
 * Themed 404 (redesign). Replaces Next's unstyled default. Renders inside the
 * root layout, so it inherits the active aesthetic + mode tokens.
 *
 * The pre-paint bootstrap script (root layout) sets `data-aesthetic` by
 * matching the pathname against a typeset whitelist; any unrecognized path —
 * i.e. exactly the 404 case — falls through to 'compiler', which would give
 * this marketing-styled page the dark-orange app aesthetic instead of the
 * typeset look its copy/design imply. Force it back to 'typeset' as soon as
 * this page mounts, before paint is visible to the user.
 */
const FORCE_TYPESET = `document.documentElement.setAttribute('data-aesthetic','typeset');document.documentElement.setAttribute('data-force-typeset','1');`

export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center bg-bg px-6 py-20 text-center text-fg">
      <script dangerouslySetInnerHTML={{ __html: FORCE_TYPESET }} />
      <p className="font-mono text-sm uppercase tracking-[0.3em] text-accent-strong">404</p>
      <h1 className="mt-4 max-w-[18ch] text-balance font-display text-[clamp(2rem,5vw,3.4rem)] font-semibold leading-[1.05] tracking-[-0.02em] text-fg">
        This page could not be found.
      </h1>
      <p className="mt-4 max-w-[42ch] font-body text-base text-fg-2">
        The link may be broken, or the page may have moved. Let&apos;s get you back on track.
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/"
          className="inline-flex items-center rounded-[var(--radius-md)] bg-accent px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
        >
          Back home
        </Link>
        <Link
          href="/try"
          className="inline-flex items-center rounded-[var(--radius-md)] border border-line-2 px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-fg transition duration-150 hover:border-accent hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
        >
          Open the studio
        </Link>
      </div>
    </div>
  )
}
