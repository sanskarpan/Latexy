'use client'

/**
 * TenantThemeSync — Feature 85F.
 *
 * Fetches GET /tenants/current-context once on mount and applies branding
 * via applyTenantTheme() so custom primary colors and logos take effect
 * before the first paint.  Renders nothing visible.
 */

import { useEffect } from 'react'
import { apiClient } from '@/lib/api-client'
import { applyTenantTheme, clearTenantTheme } from '@/lib/tenant-theme'

export default function TenantThemeSync() {
  useEffect(() => {
    apiClient.getCurrentTenantContext()
      .then(({ tenant }) => {
        if (tenant) {
          applyTenantTheme(tenant)
        } else {
          clearTenantTheme()
        }
      })
      .catch(() => {
        // Non-critical — theme injection is best-effort
      })
  }, [])

  return null
}
