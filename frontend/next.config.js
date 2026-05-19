/** @type {import('next').NextConfig} */
const withPWA = require('@ducanh2912/next-pwa').default

const nextConfig = {
  webpack: (config) => {
    // Handle canvas for react-pdf
    config.resolve.alias.canvas = false
    config.resolve.alias.encoding = false
    return config
  },

  // Expose public env vars to the browser bundle
  env: {
    NEXT_PUBLIC_APP_URL:
      process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:5180',
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030',
    NEXT_PUBLIC_WS_URL:
      process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8030',
  },
}

module.exports = withPWA({
  dest: 'public',
  // Disable service worker in dev to avoid caching surprises during development
  disable: process.env.NODE_ENV === 'development',
  fallbacks: {
    document: '/offline.html',
  },
  cacheOnFrontEndNav: true,
  aggressiveFrontEndNavCaching: true,
  reloadOnOnline: true,
  workboxOptions: {
    maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
    runtimeCaching: [
      // App shell: static assets cached with StaleWhileRevalidate
      {
        urlPattern: /^\/(_next\/static|_next\/image)/,
        handler: 'StaleWhileRevalidate',
        options: {
          cacheName: 'latexy-app-shell',
        },
      },
      // Resume API: NetworkFirst (try server, fall back to cache)
      {
        urlPattern: /\/resumes($|\?)/,
        handler: 'NetworkFirst',
        options: {
          cacheName: 'latexy-api-resumes',
          networkTimeoutSeconds: 5,
          expiration: { maxAgeSeconds: 5 * 60 },
        },
      },
      // PDF assets: CacheFirst — PDFs rarely change, serve from cache for 7 days
      {
        urlPattern: /\.pdf$/,
        handler: 'CacheFirst',
        options: {
          cacheName: 'latexy-pdf-cache',
          expiration: {
            maxEntries: 30,
            maxAgeSeconds: 7 * 24 * 60 * 60,
          },
        },
      },
    ],
  },
})(nextConfig)
