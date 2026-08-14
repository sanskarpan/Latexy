/**
 * Root-level loading fallback (redesign). Next.js renders this as the Suspense
 * boundary for the root layout's `children` slot during route-level
 * navigations/data fetches, so cross-route transitions get a consistent,
 * token-styled affordance instead of the previous page just hanging until the
 * next one is ready. Sibling to not-found.tsx / error.tsx: it renders inside
 * the root layout, so it inherits the active aesthetic + mode tokens.
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className="flex min-h-[70vh] flex-col items-center justify-center bg-bg px-6 py-20 text-center text-fg"
    >
      <span
        aria-hidden
        className="h-9 w-9 animate-spin rounded-full border-2 border-line border-t-accent motion-reduce:animate-none"
      />
      <p className="mt-5 font-ui text-sm font-medium uppercase tracking-[0.2em] text-fg-3">
        Loading…
      </p>
      <span className="sr-only">Loading page content</span>
    </div>
  )
}
