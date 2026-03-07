/** @type {import('next').NextConfig} */
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

module.exports = nextConfig
