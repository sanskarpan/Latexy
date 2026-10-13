'use client'

import dynamic from 'next/dynamic'
import { Suspense } from 'react'
import type { LatexGeneratorRecovery } from '@/hooks/useLatexGeneratorRecovery'

const LatexGeneratorPanel = dynamic(() => import('@/components/LatexGeneratorPanel'))

export default function LatexGeneratorRecoveryShell({
  recovery, active, documentId, documentContext, onInsert,
}: {
  recovery: LatexGeneratorRecovery
  active: boolean
  documentId: string
  documentContext: string
  onInsert: (latex: string) => void
}) {
  if (!recovery.mounted) return null
  // A hidden tab stays mounted. D14/leaf/C01 revocation cannot erase an
  // admitted result or local draft, and the recovery menu can revisit it.
  return (
    <div key={recovery.key} hidden={!active} className={active ? 'h-full min-h-0' : 'hidden'} data-latex-generator-recovery>
      {/* Keep a cold panel chunk inside its own boundary. Suspending the route
          would hide the source owner and retire its committed readiness. */}
      <Suspense fallback={<div role="status" className="p-4 text-xs text-fg-3">Loading generator…</div>}>
        <LatexGeneratorPanel
          documentId={documentId}
          documentContext={documentContext}
          admissionAllowed={active && recovery.canStart}
          admissionGuard={recovery.mayStart}
          insertionAllowed={recovery.mayInsert()}
          insertionGuard={recovery.mayInsert}
          onRecoveryChange={recovery.onRecoveryChange}
          onInsert={fragment => { if (recovery.mayInsert()) onInsert(fragment) }}
        />
      </Suspense>
    </div>
  )
}
