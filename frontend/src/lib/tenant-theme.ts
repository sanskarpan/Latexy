/**
 * Tenant theme injection — Feature 85F.
 *
 * Applies white-label branding (logo, primary color) from the resolved tenant
 * returned by GET /tenants/current-context.  Called once on app mount in layout.tsx.
 */

export interface TenantBranding {
  id: string
  slug: string
  name: string
  logo_url?: string | null
  primary_color?: string | null
  custom_domain?: string | null
  plan_id: string
  max_members: number
}

/**
 * Apply tenant CSS custom properties and document title to the current page.
 * Safe to call on SSR — checks for `document` before touching the DOM.
 */
export function applyTenantTheme(tenant: TenantBranding): void {
  if (typeof document === 'undefined') return

  const root = document.documentElement

  if (tenant.primary_color) {
    root.style.setProperty('--tenant-primary', tenant.primary_color)
    root.style.setProperty('--tenant-primary-rgb', hexToRgb(tenant.primary_color))
  }

  if (tenant.logo_url) {
    root.setAttribute('data-tenant-logo', tenant.logo_url)
  }

  root.setAttribute('data-tenant-slug', tenant.slug)
  document.title = `${tenant.name} | Powered by Latexy`
}

/**
 * Reset all tenant theme overrides (used when no tenant is resolved).
 */
export function clearTenantTheme(): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.style.removeProperty('--tenant-primary')
  root.style.removeProperty('--tenant-primary-rgb')
  root.removeAttribute('data-tenant-logo')
  root.removeAttribute('data-tenant-slug')
}

function hexToRgb(hex: string): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)
  if (!result) return '109 40 217' // fallback: purple-700
  return [
    parseInt(result[1], 16),
    parseInt(result[2], 16),
    parseInt(result[3], 16),
  ].join(' ')
}
