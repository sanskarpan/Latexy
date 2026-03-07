import type { ReactNode } from 'react'

export default function MarketingFrame({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <div className="surface-panel overflow-hidden">
        <main className="px-5 pb-16 pt-12 sm:px-8 sm:pb-20 sm:pt-16">{children}</main>
      </div>
    </div>
  )
}
