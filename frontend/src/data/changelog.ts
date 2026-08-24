/**
 * Changelog / shipping-log entries, newest first.
 *
 * Kept in a data module (rather than inline in the page) so the log has a
 * single source of truth that's easy to append to and could later be sourced
 * from a CMS or generated from release notes.
 */
export interface ChangelogEntry {
  date: string
  title: string
  points: string[]
}

export const changelog: ChangelogEntry[] = [
  {
    date: 'August 24, 2026',
    title: 'ATS Score Card & Trust Commitments',
    points: [
      'Multi-dimensional ATS score card breaks your score into named categories with click-to-fix deep links',
      'Academic-CV aware page-count guidance and a published no-training data commitment',
    ],
  },
  {
    date: 'August 12, 2026',
    title: 'Onboarding & Workspace Redesign',
    points: ['Faster template previews with a reworked onboarding flow', 'Refreshed workspace layout for clearer project navigation'],
  },
  {
    date: 'August 08, 2026',
    title: 'Overleaf-Style Studio Rebuild',
    points: ['Rebuilt /try as a three-pane editor, preview, and log workspace', 'Theme-aware editor, themed 404, and a cleaned-up display type system'],
  },
  {
    date: 'August 02, 2026',
    title: 'Guided Optimization & Project Import',
    points: ['Guided-intake direction fields now steer the optimization prompt', 'Import projects directly from GitHub and public URLs'],
  },
  {
    date: 'July 25, 2026',
    title: 'Admin Control Plane',
    points: ['Feature and plan toggles with role-based access control', 'Entitlement engine wired into enforcement across the API'],
  },
  {
    date: 'July 03, 2026',
    title: 'Production Readiness Layer',
    points: ['Observability core with business, compile, ATS, and LLM metrics', 'API hardening, health checks, and performance instrumentation'],
  },
  {
    date: 'March 06, 2026',
    title: 'New Premium Frontend System',
    points: ['Rebuilt marketing experience with multi-page architecture', 'Unified dark visual language across app and marketing routes'],
  },
  {
    date: 'March 04, 2026',
    title: 'Expanded Job Event Streaming',
    points: ['Improved event flow for logs, progress, and token streams', 'Enhanced reliability in queue-driven execution'],
  },
  {
    date: 'March 01, 2026',
    title: 'BYOK Provider Enhancements',
    points: ['Improved key validation flow', 'Better provider metadata support'],
  },
]
