/**
 * Service Worker Cache Strategy Config (Feature 79B).
 *
 * This file documents the Workbox runtime-caching rules that are applied
 * by @ducanh2912/next-pwa.  The actual runtime caching is configured in
 * `next.config.js` via the `runtimeCaching` option — this file serves as
 * the typed reference / single source of truth.
 *
 * Strategies:
 *  - App shell (CSS, JS)         → StaleWhileRevalidate (fast load + background update)
 *  - API, navigation and PDFs   → network only (may contain private resume data)
 *  - Offline fallback           → /offline.html (served when all strategies fail)
 */

export const SW_CACHE_STRATEGY_DOCS = {
  navigation: {
    match: "request.mode === 'navigate'",
    handler: 'NetworkOnly',
    fallback: '/offline.html',
  },
  appShell: {
    urlPattern: /\/_next\/(?:static|image)\//,
    handler: 'StaleWhileRevalidate',
    cacheName: 'latexy-app-shell',
  },
  excludedPrivateData: ['API responses', 'navigation responses', 'PDF responses'],
} as const
