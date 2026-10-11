'use client'

import type { useEngineCapability } from '@/hooks/useEngineCapability'

export default function EngineCapabilityNotice({ capability, pdfImport = false }: { capability: ReturnType<typeof useEngineCapability>; pdfImport?: boolean }) {
  if (capability.status === 'supported') return null
  const message = pdfImport
    ? capability.status === 'loading'
      ? 'Checking PDF import availability. Your selected file and title are preserved.'
      : capability.status === 'unsupported'
        ? 'PDF import is not available on this server yet. Your selected file and title are preserved. Choose another file or create a resume from a template to continue.'
        : capability.reason === 'authorization'
          ? 'Access to PDF import could not be verified. Check your sign-in or permissions, then retry. Your selected file and title are preserved.'
          : 'PDF import availability could not be checked. Retry when the connection is available. Your selected file and title are preserved.'
    : capability.status === 'loading'
    ? 'Checking availability of resume fields… You can choose Source to keep editing.'
    : capability.status === 'unsupported'
      ? 'Resume fields are not available on this server yet. Source editing and PDF compilation remain available. Your content and editor preference are preserved.'
      : capability.reason === 'authorization'
        ? 'Access to resume fields could not be verified. Check your sign-in or permissions, then retry. Your document is preserved.'
        : 'Resume fields could not be checked. Retry when the connection is available, or choose Source to keep editing. Your document is preserved.'
  return <div role={capability.status === 'error' ? 'alert' : 'status'} className="flex shrink-0 items-center gap-3 border-b border-line bg-surface-2 px-3 py-2 text-xs text-fg-2">
    <p className="flex-1">{message}</p>
    {capability.status !== 'loading' && <button type="button" onClick={capability.retry} disabled={capability.checking}
      className="shrink-0 underline disabled:opacity-50">{capability.checking ? 'Checking…' : pdfImport ? 'Retry PDF import' : 'Retry resume fields'}</button>}
  </div>
}
