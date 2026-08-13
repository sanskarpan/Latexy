'use client'

export function Skeleton({ className }: { className?: string }) {
  return (
    <div aria-hidden="true" className={`animate-pulse rounded-[var(--radius-sm)] bg-surface-2 ${className}`} />
  )
}

/**
 * Announces the loading state to assistive tech. Wrap any group of decorative
 * <Skeleton /> shapes so screen readers hear "Loading…" instead of silence.
 */
export function SkeletonGroup({ label = 'Loading…', className, children }: { label?: string; className?: string; children: React.ReactNode }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className={className}>
      {children}
      <span className="sr-only">{label}</span>
    </div>
  )
}

export function CardSkeleton() {
  return (
    <SkeletonGroup className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 space-y-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-4 rounded-full" />
      </div>
      <div className="flex items-baseline gap-2">
        <Skeleton className="h-8 w-16" />
        <Skeleton className="h-3 w-12" />
      </div>
    </SkeletonGroup>
  )
}

export function ResumeCardSkeleton() {
  return (
    <SkeletonGroup className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 space-y-6">
      <div className="flex items-start justify-between">
        <Skeleton className="h-12 w-12 rounded-lg" />
        <Skeleton className="h-6 w-6" />
      </div>
      <div className="space-y-2">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
      </div>
      <div className="flex gap-3">
        <Skeleton className="h-8 flex-1 rounded-lg" />
        <Skeleton className="h-8 flex-1 rounded-lg" />
      </div>
    </SkeletonGroup>
  )
}
