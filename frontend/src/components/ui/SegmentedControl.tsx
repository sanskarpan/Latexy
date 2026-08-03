'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

/** A single selectable segment. */
export interface SegmentedControlOption<T extends string = string> {
  /** Stable value emitted through `onChange` when selected. */
  value: T
  /** Visible label rendered inside the segment. */
  label: React.ReactNode
  /** Optional leading icon element. */
  icon?: React.ReactNode
  /** When true the segment cannot be selected or focused. */
  disabled?: boolean
}

export interface SegmentedControlProps<T extends string = string>
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  /** Ordered list of selectable segments. */
  options: SegmentedControlOption<T>[]
  /** Currently selected value (controlled). */
  value: T
  /** Called with the next value when the selection changes. */
  onChange: (value: T) => void
  /** Accessible label describing the group. */
  'aria-label'?: string
}

/**
 * SegmentedControl — a controlled, single-select segmented control.
 *
 * Renders a `role="radiogroup"` track of `role="radio"` segments with
 * roving-tabindex keyboard support (Arrow keys, Home/End) matching the
 * WAI-ARIA radio pattern. The active segment is highlighted with the accent
 * surface. Fully theme-token driven and accessible. Pass `aria-label` (or an
 * external `aria-labelledby`) so the group has an accessible name.
 */
function SegmentedControlInner<T extends string = string>(
  { options, value, onChange, className, 'aria-label': ariaLabel, ...props }: SegmentedControlProps<T>,
  ref: React.ForwardedRef<HTMLDivElement>
) {
  const tabRefs = React.useRef<(HTMLButtonElement | null)[]>([])

  const enabledIndexes = React.useMemo(
    () => options.map((o, i) => (o.disabled ? -1 : i)).filter((i) => i !== -1),
    [options]
  )

  const selectedIndex = options.findIndex((o) => o.value === value)
  // The index that owns tabindex=0 (roving). Fall back to first enabled.
  const activeIndex =
    selectedIndex !== -1 && !options[selectedIndex]?.disabled
      ? selectedIndex
      : enabledIndexes[0] ?? -1

  const focusIndex = (index: number) => {
    const el = tabRefs.current[index]
    if (el) el.focus()
  }

  const moveTo = (index: number) => {
    const option = options[index]
    if (!option || option.disabled) return
    focusIndex(index)
    onChange(option.value)
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (enabledIndexes.length === 0) return
    const pos = enabledIndexes.indexOf(index)

    let nextPos: number | null = null
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        nextPos = (pos + 1) % enabledIndexes.length
        break
      case 'ArrowLeft':
      case 'ArrowUp':
        nextPos = (pos - 1 + enabledIndexes.length) % enabledIndexes.length
        break
      case 'Home':
        nextPos = 0
        break
      case 'End':
        nextPos = enabledIndexes.length - 1
        break
      default:
        return
    }

    event.preventDefault()
    moveTo(enabledIndexes[nextPos])
  }

  return (
    <div
      ref={ref}
      role="radiogroup"
      aria-label={ariaLabel}
      aria-orientation="horizontal"
      className={cn(
        'inline-flex items-center gap-1 rounded-[var(--radius-md)] bg-surface-2 p-1 font-ui',
        className
      )}
      {...props}
    >
      {options.map((option, index) => {
        const isSelected = option.value === value
        const isTabStop = index === activeIndex
        return (
          <button
            key={option.value}
            ref={(el) => {
              tabRefs.current[index] = el
            }}
            type="button"
            role="radio"
            aria-checked={isSelected}
            disabled={option.disabled}
            tabIndex={isTabStop ? 0 : -1}
            onClick={() => moveTo(index)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            className={cn(
              'inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-sm)] px-3 py-1.5 text-sm font-medium',
              'transition duration-150 motion-reduce:transition-none',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
              'disabled:pointer-events-none disabled:opacity-50',
              isSelected
                ? 'bg-accent text-accent-fg shadow-sm'
                : 'text-fg-2 hover:bg-surface hover:text-fg'
            )}
          >
            {option.icon ? (
              <span className="inline-flex shrink-0 items-center" aria-hidden="true">
                {option.icon}
              </span>
            ) : null}
            <span>{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}

/**
 * Forward-ref wrapper preserving the generic value type of the options.
 */
const SegmentedControl = React.forwardRef(SegmentedControlInner) as (<T extends string = string>(
  props: SegmentedControlProps<T> & { ref?: React.ForwardedRef<HTMLDivElement> }
) => React.ReactElement) & { displayName?: string }

SegmentedControl.displayName = 'SegmentedControl'

export { SegmentedControl }
export default SegmentedControl
