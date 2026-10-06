import { NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const revalidate = 0

const SHA_PATTERN = /^[0-9a-f]{40}$/

/**
 * Public, cache-proof deployment identity used by the post-CI certification.
 * Vercel exposes VERCEL_GIT_COMMIT_SHA at runtime; self-hosted images inject
 * the exact source SHA as BUILD_VERSION during their Docker build.
 */
export function GET() {
  const vercelSha = process.env.VERCEL_GIT_COMMIT_SHA?.trim()
  const buildVersion = process.env.BUILD_VERSION?.trim()
  const normalizedVercelSha = vercelSha?.toLowerCase()
  const normalizedBuildVersion = buildVersion?.toLowerCase()
  // Do not fall back to a Docker value when Vercel supplied a malformed
  // identity: that would certify an unrelated deployment as the Vercel one.
  const commitSha = normalizedVercelSha
    ? SHA_PATTERN.test(normalizedVercelSha)
      ? normalizedVercelSha
      : undefined
    : normalizedBuildVersion && SHA_PATTERN.test(normalizedBuildVersion)
      ? normalizedBuildVersion
      : undefined
  const source = normalizedVercelSha
    ? commitSha
      ? 'vercel'
      : 'unknown'
    : commitSha
      ? 'build'
      : 'unknown'

  return NextResponse.json(
    { commitSha: commitSha || null, source },
    {
      status: commitSha ? 200 : 503,
      headers: {
        'Cache-Control': 'no-store, max-age=0',
        'Vercel-CDN-Cache-Control': 'no-store',
      },
    },
  )
}
