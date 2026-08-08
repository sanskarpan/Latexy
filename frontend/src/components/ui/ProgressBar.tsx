import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * ProgressBar — a horizontal progress indicator.
 *
 * Provide `value` (0–100) for a determinate bar, or omit it for an
 * indeterminate state that renders an animated stripe (with a
 * `motion-reduce` fallback). An optional `label` is shown above the track
 * and wired to the bar via `aria-label` for assistive technology.
 */
export interface ProgressBarProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'role'> {
  /** Completion percentage from 0–100. Omit for an indeterminate bar. */
  value?: number
  /** Accessible/visible label describing what is progressing. */
  label?: string
}

const ProgressBar = React.forwardRef<HTMLDivElement, ProgressBarProps>(
  ({ className, value, label, ...props }, ref) => {
    const isIndeterminate = value === undefined
    const clamped = isIndeterminate
      ? undefined
      : Math.min(100, Math.max(0, value))
    // role="progressbar" requires an accessible name; fall back so the bar
    // is never left unnamed when no `label` is supplied.
    const accessibleName = label ?? 'Progress'

    return (
      <div ref={ref} className={cn('w-full', className)} {...props}>
        {(label || !isIndeterminate) && (
          <div className="mb-1.5 flex items-center justify-between font-ui text-xs text-fg-2">
            {label ? <span>{label}</span> : <span />}
            {!isIndeterminate && (
              <span className="tabular-nums text-fg-3">{Math.round(clamped!)}%</span>
            )}
          </div>
        )}
        <div
          role="progressbar"
          aria-label={accessibleName}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={isIndeterminate ? undefined : clamped}
          aria-valuetext={isIndeterminate ? 'Loading' : undefined}
          aria-busy={isIndeterminate || undefined}
          className="relative h-2 w-full overflow-hidden rounded-[var(--radius-pill)] bg-surface-2"
        >
          {isIndeterminate ? (
            <div
              className={cn(
                'absolute inset-y-0 left-0 w-2/5 rounded-[var(--radius-pill)] bg-accent',
                'animate-progress-indeterminate',
                'motion-reduce:animate-none motion-reduce:w-full motion-reduce:translate-x-0 motion-reduce:opacity-60'
              )}
            />
          ) : (
            <div
              className="h-full rounded-[var(--radius-pill)] bg-accent transition-[width] duration-150 motion-reduce:transition-none"
              style={{ width: `${clamped}%` }}
            />
          )}
        </div>
      </div>
    )
  }
)
ProgressBar.displayName = 'ProgressBar'

export { ProgressBar }
export default ProgressBar
