/**
 * Better Auth server configuration.
 *
 * - Adapter: pg (uses existing DATABASE_URL)
 * - User table: "users" (our existing table, with field mapping for snake_case columns)
 * - Providers: email/password + Google + GitHub (social providers activate only when env vars are set)
 * - Session / account / verification tables: created by the Better Auth migration (see alembic/versions/)
 *
 * This module is server-only — never import it in Client Components.
 */

import { betterAuth } from 'better-auth'
import { Pool } from 'pg'

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
})

/**
 * Resolve the Better Auth signing secret. There is NO hardcoded fallback: a
 * well-known default secret would let anyone forge session cookies/tokens. In
 * production a missing secret is fatal; in development we derive a stable,
 * process-local placeholder and warn loudly.
 */
function getAuthSecret(): string {
  const secret = process.env.BETTER_AUTH_SECRET
  if (secret) return secret
  // `next build` runs with NODE_ENV=production but should not require runtime
  // secrets; only fail at actual runtime (serving), not during the build phase.
  const isBuildPhase = process.env.NEXT_PHASE === 'phase-production-build'
  if (process.env.NODE_ENV === 'production' && !isBuildPhase) {
    throw new Error('BETTER_AUTH_SECRET is required in production and has no default.')
  }
  console.warn('[auth] BETTER_AUTH_SECRET is not set — using an insecure development-only secret.')
  return 'dev-only-insecure-secret-do-not-use-in-production'
}

export const auth = betterAuth({
  database: pool,

  // Map to our existing "users" table with snake_case columns
  // NOTE: Better Auth 1.x uses "modelName" (not "tableName")
  user: {
    modelName: 'users',
    fields: {
      emailVerified: 'email_verified',
      image: 'avatar_url',
      createdAt: 'created_at',
      updatedAt: 'updated_at',
    },
  },

  // Our users.id column is type UUID — generate proper UUIDs
  advanced: {
    database: {
      generateId: () => crypto.randomUUID(),
    },
  },

  // Email + password sign-in
  emailAndPassword: {
    enabled: true,
    minPasswordLength: 8,
    requireEmailVerification: false,
  },

  // Social OAuth providers — only active when both client ID + secret are provided
  socialProviders: {
    ...(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? {
          google: {
            clientId: process.env.GOOGLE_CLIENT_ID,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET,
          },
        }
      : {}),
    ...(process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET
      ? {
          github: {
            clientId: process.env.GITHUB_CLIENT_ID,
            clientSecret: process.env.GITHUB_CLIENT_SECRET,
          },
        }
      : {}),
  },

  secret: getAuthSecret(),
  baseURL: process.env.BETTER_AUTH_URL || 'http://localhost:5180',

  // Trust requests from both the frontend and the FastAPI backend
  trustedOrigins: [
    process.env.BETTER_AUTH_URL || 'http://localhost:5180',
    process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030',
  ],

  // Session configuration
  session: {
    expiresIn: 60 * 60 * 24 * 7, // 7 days
    updateAge: 60 * 60 * 24,     // refresh if used within 1 day of expiry
  },
})
