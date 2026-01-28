import { createEnv } from '@t3-oss/env-nextjs'
import { env as runtimeEnv } from 'next-runtime-env'
import { z } from 'zod'

/**
 * Universal environment variable getter that works in both client and server contexts.
 * - Client-side: Uses next-runtime-env for runtime injection (supports Docker runtime vars)
 * - Server-side: Falls back to process.env when runtimeEnv returns undefined
 * - Provides seamless Docker runtime variable support for NEXT_PUBLIC_ vars
 */
const getEnv = (variable: string) => runtimeEnv(variable) ?? process.env[variable]

// biome-ignore format: keep alignment for readability
export const env = createEnv({
  skipValidation: true,

  server: {
    // Authentication
    DISABLE_REGISTRATION:                  z.boolean().optional(),                 // Flag to disable new user registration

    // Email & Communication
    EMAIL_VERIFICATION_ENABLED:            z.boolean().optional(),                 // Enable email verification for user registration and login (defaults to false)
    RESEND_API_KEY:                        z.string().min(1).optional(),           // Resend API key for transactional emails
    FROM_EMAIL_ADDRESS:                    z.string().min(1).optional(),           // Complete from address (e.g., "JD <noreply@domain.com>" or "noreply@domain.com")
    EMAIL_DOMAIN:                          z.string().min(1).optional(),           // Domain for sending emails (fallback when FROM_EMAIL_ADDRESS not set)
    AZURE_ACS_CONNECTION_STRING:           z.string().optional(),                  // Azure Communication Services connection string
  },

  client: {
    // Core Application URLs - Required for frontend functionality
    NEXT_PUBLIC_APP_URL:                   z.string().url().optional(),            // Base URL of the application (e.g., https://www.jd.ai)
  },

  // Variables available on both server and client
  shared: {
    NODE_ENV:                              z.enum(['development', 'test', 'production']).optional(), // Runtime environment
  },

  experimental__runtimeEnv: {
    NEXT_PUBLIC_APP_URL: process.env.NEXT_PUBLIC_APP_URL,
    NODE_ENV: process.env.NODE_ENV,
  },
})

// Need this utility because t3-env is returning string for boolean values.
export const isTruthy = (value: string | boolean | number | undefined) =>
  typeof value === 'string' ? value.toLowerCase() === 'true' || value === '1' : Boolean(value)

// Utility to check if a value is explicitly false (defaults to false only if explicitly set)
export const isFalsy = (value: string | boolean | number | undefined) =>
  typeof value === 'string' ? value.toLowerCase() === 'false' || value === '0' : value === false

export { getEnv }
