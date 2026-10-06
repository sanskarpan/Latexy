/** @type {import('next').NextConfig} */
const withPWA = require('@ducanh2912/next-pwa').default

const nextConfig = {
  // Browser tests run Next from a disposable copy, so their generated `.next`
  // tree cannot collide with the shared checkout. Normal dev/build keeps the
  // conventional `.next` path used by the standalone artifact checks.
  distDir: process.env.NEXT_DIST_DIR || '.next',
  output: 'standalone',
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
          {
            key: 'Content-Security-Policy',
            // Keep this baseline deliberately narrow: frame/base/object
            // restrictions are safe with Next's inline bootstrap and Monaco's
            // workers, while a full source allowlist needs per-request nonces.
            value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
          },
        ],
      },
    ]
  },
  // @monaco-editor/react 4.7 keeps a disposed editor service across React's
  // development effect replay. Opening a second Monaco surface (for example,
  // the version diff modal) then crashes the whole route. React has no
  // subtree-level Strict Mode opt-out, so keep replay disabled until the
  // wrapper is replay-safe; production rendering is unaffected.
  reactStrictMode: false,
  webpack: (config) => {
    // Handle canvas for react-pdf
    config.resolve.alias.canvas = false
    config.resolve.alias.encoding = false
    return config
  },
  // Development intentionally uses Turbopack. The aliases above are only
  // needed by the production Webpack server bundle. Make Turbopack's normal
  // development module-id strategy explicit so Next recognises this split as
  // configured rather than warning about an accidental Webpack-only setup.
  turbopack: { moduleIds: 'named' },

  // Expose public env vars to the browser bundle
  env: {
    NEXT_PUBLIC_APP_URL:
      process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:5180',
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030',
    NEXT_PUBLIC_WS_URL:
      process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8030',
    // OAuth button visibility — set to 'true' only when the matching provider
    // is configured server-side (GOOGLE_CLIENT_ID / GITHUB_CLIENT_ID). Default
    // '' → buttons hidden, so no dead OAuth buttons are shown.
    NEXT_PUBLIC_OAUTH_GOOGLE_ENABLED:
      process.env.NEXT_PUBLIC_OAUTH_GOOGLE_ENABLED || '',
    NEXT_PUBLIC_OAUTH_GITHUB_ENABLED:
      process.env.NEXT_PUBLIC_OAUTH_GITHUB_ENABLED || '',
  },
}

module.exports = withPWA({
  dest: 'public',
  // Disable service worker in dev to avoid caching surprises during development
  disable: process.env.NODE_ENV === 'development',
  fallbacks: {
    document: '/offline.html',
  },
  // Monaco is a desktop-only 15 MB public asset tree. The mobile editor uses
  // CodeMirror, so downloading every Monaco language during PWA installation
  // wastes bandwidth and storage. It remains available online on desktop.
  publicExcludes: ['!noprecache/**/*', '!monaco/**/*'],
  // Route/RSC responses may represent authenticated pages or contain private
  // share tokens. Cache only immutable app assets, never navigations.
  cacheOnFrontEndNav: false,
  aggressiveFrontEndNavCaching: false,
  // Let the editor's online-state effect flush owner-scoped drafts and queued
  // compiles before any navigation. next-pwa's reloadOnOnline handler calls
  // location.reload() unconditionally and can discard an in-flight reconnect.
  reloadOnOnline: false,
  workboxOptions: {
    maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
    runtimeCaching: [
      // Register navigations so next-pwa can attach the document fallback.
      // NetworkOnly is deliberate: authenticated page/RSC responses must not
      // survive logout in Cache Storage.
      {
        urlPattern: ({ request }) => request.mode === 'navigate',
        handler: 'NetworkOnly',
        // next-pwa attaches its handlerDidError fallback plugin only when the
        // route has an options object.
        options: {},
      },
      // App shell: static assets cached with StaleWhileRevalidate. Workbox
      // tests RegExp routes against the full URL, so the matcher must not be
      // anchored at the pathname's leading slash.
      {
        urlPattern: /\/_next\/(?:static|image)\//,
        handler: 'StaleWhileRevalidate',
        options: {
          cacheName: 'latexy-app-shell',
        },
      },
      // Never cache authenticated API payloads or PDFs. Cache Storage is not
      // user-partitioned and survives logout. Offline documents belong in the
      // explicitly owner-scoped IndexedDB store, not a URL-wide cache.
    ],
  },
})(nextConfig)
