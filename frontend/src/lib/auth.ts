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

  secret: process.env.BETTER_AUTH_SECRET || 'change-me-in-production',
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
