import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    projects: [
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
    ],
  },
})
