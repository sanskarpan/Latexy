'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Toggle — a controlled accessible switch.
 *
 * Renders a `role="switch"` button whose `aria-checked` reflects `checked`.
 * Space/Enter (native button activation) toggles state via `onChange`. The
 * visible control sits inside a >=44px hit area for comfortable touch targets;
 * the track is `bg-surface-2` when off and `bg-accent` when on, with a sliding
 * thumb. When `disabled`, the control is dimmed and non-interactive.
 */
export interface ToggleProps {
  /** Whether the switch is on (controlled). */
  checked: boolean
  /** Called with the next checked value when the user toggles. */
  onChange: (checked: boolean) => void
  /** Optional visible label rendered beside the switch and wired via aria. */
  label?: string
  /** Disables interaction and dims the control. */
  disabled?: boolean
  /** Merged onto the outermost element, last. */
  className?: string
  /** Accessible name when no visible `label` is provided. */
  'aria-label'?: string
}

const Toggle = React.forwardRef<HTMLButtonElement, ToggleProps>(
  (
    { checked, onChange, label, disabled = false, className, 'aria-label': ariaLabel, ...props },
    ref
  ) => {
    const generatedId = React.useId()
    const labelId = label ? `${generatedId}-label` : undefined

    const handleClick = () => {
      if (disabled) return
      onChange(!checked)
    }

    const control = (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-disabled={disabled || undefined}
        aria-labelledby={labelId}
        aria-label={label ? undefined : ariaLabel}
        disabled={disabled}
        onClick={handleClick}
        className={cn(
          // >=44px hit area with the visible track centered inside.
          'group relative inline-flex h-11 w-14 shrink-0 cursor-pointer items-center justify-center',
          'rounded-[var(--radius-pill)]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
          'disabled:cursor-not-allowed disabled:opacity-50',
          !label && className
        )}
        {...props}
      >
        {/* Track */}
        <span
          aria-hidden="true"
          className={cn(
            'pointer-events-none relative block h-6 w-11 rounded-[var(--radius-pill)] border transition duration-150 motion-reduce:transition-none',
            checked ? 'border-accent bg-accent' : 'border-line-2 bg-surface-2'
          )}
        >
          {/* Thumb — color tracks the surface it sits on so the off/on
              state stays clearly perceivable in every theme variant:
              bg-accent-fg contrasts against the accent track, bg-fg-2
              against the surface-2 track. */}
          <span
            className={cn(
              'absolute top-1/2 left-0.5 h-5 w-5 -translate-y-1/2 rounded-[var(--radius-pill)] shadow-sm transition duration-150 motion-reduce:transition-none',
              checked ? 'translate-x-5 bg-accent-fg' : 'translate-x-0 bg-fg-2'
            )}
          />
        </span>
      </button>
    )

    if (!label) return control

    return (
      <span className={cn('inline-flex items-center gap-2', className)}>
        {control}
        <label
          id={labelId}
          onClick={handleClick}
          className={cn(
            'select-none font-ui text-sm text-fg-2',
            disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
          )}
        >
          {label}
        </label>
      </span>
    )
  }
)

Toggle.displayName = 'Toggle'

export { Toggle }
export default Toggle
