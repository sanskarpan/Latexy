'use client'

import { useEffect } from 'react'
import { usePathname } from 'next/navigation'
import { useReportWebVitals } from 'next/web-vitals'

import { normalizeRoute, trackBusinessEvent, trackWebVital } from '@/lib/telemetry'

export default function WebVitalsReporter() {
  const pathname = usePathname()
  const route = normalizeRoute(pathname)

  useReportWebVitals((metric) => {
    trackWebVital(metric, route)
  })

  useEffect(() => {
    trackBusinessEvent('page_view', route)
  }, [route])

  return null
}
