import { defineConfig } from 'tsup'
import { readFileSync } from 'node:fs'

const { version } = JSON.parse(readFileSync('./package.json', 'utf-8')) as { version: string }

export default defineConfig({
  entry: { cli: 'src/cli.tsx' },
  format: ['esm'],
  target: 'node22',
  platform: 'node',
  bundle: true,
  clean: true,
  dts: false,
  sourcemap: true,
  banner: { js: '#!/usr/bin/env node' },
  external: [],
  define: {
    __LATEXY_VERSION__: JSON.stringify(version),
  },
})
