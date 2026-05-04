/**
 * Service Worker Cache Strategy Config (Feature 79B).
 *
 * This file documents the Workbox runtime-caching rules that are applied
 * by @ducanh2912/next-pwa.  The actual runtime caching is configured in
 * `next.config.js` via the `runtimeCaching` option — this file serves as
 * the typed reference / single source of truth.
 *
 * Strategies:
 *  - App shell (HTML, CSS, JS)  → StaleWhileRevalidate (fast load + background update)
 *  - API GET /resumes           → NetworkFirst, cache 5 min (always try network first)
 *  - MinIO PDF assets           → CacheFirst, cache 7 days (PDFs rarely change)
 *  - Offline fallback           → /offline.html (served when all strategies fail)
 */

export const SW_CACHE_STRATEGY_DOCS = {
  appShell: {
    urlPattern: /^\/(_next\/static|_next\/image)/,
    handler: 'StaleWhileRevalidate',
    cacheName: 'latexy-app-shell',
  },
  resumeApi: {
    urlPattern: /^https?:\/\/.*\/resumes($|\?)/,
    handler: 'NetworkFirst',
    cacheName: 'latexy-api-resumes',
    networkTimeoutSeconds: 5,
    expireMaxAgeSeconds: 5 * 60,
  },
  pdfAssets: {
    urlPattern: /\.pdf$/,
    handler: 'CacheFirst',
    cacheName: 'latexy-pdf-cache',
    expireMaxAgeSeconds: 7 * 24 * 60 * 60,
    expireMaxEntries: 30,
  },
} as const
