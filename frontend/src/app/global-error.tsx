'use client'

import { useEffect } from 'react'

/**
 * Root error boundary (redesign). This catches errors thrown by the root layout
 * itself, so it REPLACES the entire document — no root layout, no global tokens.
 * Styles are inlined to visually approximate the dark theme, keeping it a sibling
 * of not-found.tsx / error.tsx even when the token pipeline is unavailable.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])

  const mono =
    'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace'
  const sans =
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '80px 24px',
          textAlign: 'center',
          backgroundColor: '#0B0B0D',
          color: '#ECEAE4',
          fontFamily: sans,
          WebkitFontSmoothing: 'antialiased',
        }}
      >
        <p
          style={{
            margin: 0,
            fontFamily: mono,
            fontSize: '13px',
            textTransform: 'uppercase',
            letterSpacing: '0.3em',
            color: '#F0A250',
          }}
        >
          500 · Error
        </p>
        <h1
          style={{
            margin: '16px 0 0',
            maxWidth: '18ch',
            fontSize: 'clamp(2rem, 5vw, 3.4rem)',
            fontWeight: 600,
            lineHeight: 1.05,
            letterSpacing: '-0.02em',
            color: '#ECEAE4',
          }}
        >
          Something broke on our end.
        </h1>
        <p
          style={{
            margin: '16px 0 0',
            maxWidth: '42ch',
            fontSize: '16px',
            lineHeight: 1.6,
            color: '#A7A49C',
          }}
        >
          A core part of the app failed to load. This one is on us — try reloading, or head back
          home and start fresh.
        </p>
        <div
          style={{
            marginTop: '32px',
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '12px',
          }}
        >
          <button
            type="button"
            onClick={() => reset()}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              border: 'none',
              cursor: 'pointer',
              borderRadius: '8px',
              padding: '12px 24px',
              fontFamily: sans,
              fontSize: '14px',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              backgroundColor: '#F0A250',
              color: '#1C1200',
            }}
          >
            Try again
          </button>
          <a
            href="/"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              borderRadius: '8px',
              padding: '12px 24px',
              fontFamily: sans,
              fontSize: '14px',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              textDecoration: 'none',
              border: '1px solid #33333B',
              color: '#ECEAE4',
            }}
          >
            Back home
          </a>
        </div>
      </body>
    </html>
  )
}
