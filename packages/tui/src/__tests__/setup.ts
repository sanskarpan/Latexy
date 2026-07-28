// Vitest global setup — suppress Ink's alternate-screen escape codes in tests
process.env['CI'] = 'true'

// tsup injects this via `define`; vitest does not, so stand it in for component tests
;(globalThis as Record<string, unknown>)['__LATEXY_VERSION__'] = '0.0.0-test'
