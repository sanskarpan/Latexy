import { defineWorkspace } from 'vitest/config'

export default defineWorkspace([
  {
    test: {
      name: 'unit',
      include: ['src/__tests__/*.test.{ts,tsx}'],
      environment: 'node',
      globals: true,
      setupFiles: ['./src/__tests__/setup.ts'],
      testTimeout: 15000,
    },
  },
  {
    test: {
      name: 'e2e',
      include: ['src/__tests__/e2e/**/*.test.{ts,tsx}'],
      environment: 'node',
      globals: true,
      setupFiles: ['./src/__tests__/setup.ts'],
      testTimeout: 30000,
    },
  },
])
