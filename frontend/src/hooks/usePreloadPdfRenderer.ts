'use client'

import { useEffect } from 'react'
import { loadPdfRenderer } from '@/lib/pdf-renderer-loader'

/** Warm the browser-only PDF.js chunk while the user is preparing a preview. */
export function usePreloadPdfRenderer() {
  useEffect(() => { void loadPdfRenderer().catch(() => undefined) }, [])
}
