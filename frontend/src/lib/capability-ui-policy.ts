/** Explicit client enforcement points. API-backed actions are additionally enforced
 * by the server; this catalog makes the UI policy inspectable and testable.
 */
export const CLIENT_CAPABILITY_CONTROLS = {
  a06: ['app/workspace/page.tsx', 'components/onboarding/OnboardingFlow.tsx'],
  a09: ['app/try/page.tsx', 'components/onboarding/OnboardingFlow.tsx'],
  b04: ['components/onboarding/OnboardingFlow.tsx'],
  b03: ['app/workspace/page.tsx'],
  b07: ['app/workspace/new/page.tsx', 'components/ExportDropdown.tsx'],
  b08: ['components/CapabilityRouteBoundary.tsx'],
  b09: ['app/workspace/builder/[resumeId]/page.tsx'],
  b10: ['app/workspace/[resumeId]/edit/page.tsx'],
  b12: ['components/CapabilityRouteBoundary.tsx'],
  b13: ['components/CapabilityRouteBoundary.tsx'],
  c02: ['components/LaTeXEditor.tsx', 'app/workspace/[resumeId]/edit/page.tsx'],
  c03: ['components/LaTeXEditor.tsx'],
  c04: ['components/LaTeXEditor.tsx', 'app/workspace/[resumeId]/edit/page.tsx'],
  c06: ['components/LaTeXEditor.tsx', 'app/workspace/[resumeId]/edit/page.tsx', 'app/try/page.tsx'],
  c10: ['components/PDFPreview.tsx', 'components/LaTeXEditor.tsx', 'app/workspace/[resumeId]/edit/page.tsx', 'app/try/page.tsx'],
  c11: ['components/PDFPreview.tsx'],
  c14: ['app/workspace/[resumeId]/edit/page.tsx'],
  c15: ['app/workspace/[resumeId]/edit/page.tsx'],
  c17: ['components/LaTeXEditor.tsx', 'app/workspace/[resumeId]/edit/page.tsx'],
  c18: ['app/workspace/[resumeId]/edit/page.tsx'],
  c19: ['app/workspace/[resumeId]/edit/page.tsx'],
  c20: ['app/workspace/[resumeId]/edit/page.tsx'],
  c21: ['app/workspace/[resumeId]/edit/page.tsx'],
  c24: ['app/workspace/[resumeId]/edit/page.tsx'],
  d25: ['components/byok/APIKeyManager.tsx'],
  e05: ['app/tracker/page.tsx', 'components/AddApplicationModal.tsx'],
  e06: ['app/tracker/page.tsx'],
  e07: ['app/tracker/page.tsx'],
  e08: ['app/tracker/page.tsx'],
  e09: ['app/tracker/page.tsx'],
  e10: ['app/tracker/page.tsx'],
  f01: ['components/ShareResumeModal.tsx'],
  f02: ['components/ShareResumeModal.tsx'],
  f03: ['components/ShareResumeModal.tsx'],
  g01: ['app/settings/page.tsx', 'app/workspace/[resumeId]/edit/page.tsx'],
  g05: ['app/settings/page.tsx', 'app/workspace/[resumeId]/edit/page.tsx'],
  g06: ['app/settings/page.tsx'],
  g07: ['app/settings/page.tsx'],
  g08: ['app/settings/page.tsx'],
  h08: ['app/developer/page.tsx'],
  e13: ['app/tracker/page.tsx', 'app/api/extension/entitlements/route.ts', '../../packages/browser-extension/capabilities.js', '../../packages/browser-extension/popup.js', '../../packages/browser-extension/bridge.js'],
  d02: ['app/workspace/[resumeId]/optimize/page.tsx'],
  d03: ['app/workspace/[resumeId]/optimize/page.tsx', 'app/try/page.tsx'],
  d12: ['app/workspace/[resumeId]/edit/page.tsx'],
  d16: ['app/workspace/[resumeId]/edit/page.tsx'],
  d23: ['app/workspace/[resumeId]/optimize/page.tsx'],
} as const

export const CAPABILITY_ROUTES = [
  { pattern: '^/templates(?:/|$)', feature: 'b04' },
  { pattern: '^/workspace/builder(?:/|$)', feature: 'b08' },
  { pattern: '^/workspace/variant(?:/|$)', feature: 'b12' },
  { pattern: '^/workspace/merge/?$', feature: 'b13' },
  { pattern: '^/workspace/[^/]+/optimize/?$', feature: 'd01' },
  { pattern: '^/workspace/[^/]+/batch-tailor/?$', feature: 'd05' },
  { pattern: '^/workspace/[^/]+/career/?$', feature: 'e04' },
] as const

export function capabilityForRoute(pathname: string): string | null {
  return CAPABILITY_ROUTES.find(({ pattern }) => new RegExp(pattern).test(pathname))?.feature ?? null
}

/** PDF and source are data-access escapes, even when conversion is disabled. */
export function exportCapabilities(format: string): string[] {
  if (format === 'pdf' || format === 'tex') return []
  if (format === 'svg' || format === 'jpeg') return ['h02']
  if (format === 'canva' || format === 'figma') return ['h03']
  if (format === 'email') return ['h05']
  if (format === 'google_drive') return ['g06']
  if (format === 'json') return ['h01', 'b07']
  return ['h01']
}
