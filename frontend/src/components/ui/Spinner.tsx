import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const spinnerVariants = cva(
  'animate-spin motion-reduce:animate-none text-accent',
  {
    variants: {
      size: {
        sm: 'h-4 w-4',
        md: 'h-6 w-6',
        lg: 'h-8 w-8',
      },
    },
    defaultVariants: {
      size: 'md',
    },
  }
)

export interface SpinnerProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, 'role'>,
    VariantProps<typeof spinnerVariants> {
  /** Accessible label announced to assistive tech. Defaults to "Loading". */
  label?: string
}

/**
 * Spinner — an accessible SVG loading indicator.
 *
 * Renders a `role="status"` wrapper with an `animate-spin` SVG that strokes in
 * `currentColor` (inherits `text-accent` by default). Respects reduced-motion
 * via `motion-reduce:animate-none`. A single visually hidden label supplies the
 * accessible name and live-region announcement for assistive technology.
 *
 * @example
 * <Spinner size="lg" />
 */
const Spinner = React.forwardRef<HTMLSpanElement, SpinnerProps>(
  ({ className, size, label = 'Loading', ...props }, ref) => {
    return (
      <span
        ref={ref}
        role="status"
        className={cn('inline-flex items-center justify-center', className)}
        {...props}
      >
        <svg
          className={cn(spinnerVariants({ size }))}
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
          focusable="false"
        >
          <circle
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="3"
            className="opacity-25"
          />
          <path
            d="M12 2a10 10 0 0 1 10 10"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            className="opacity-90"
          />
        </svg>
        <span className="sr-only">{label}</span>
      </span>
    )
  }
)
Spinner.displayName = 'Spinner'

export { Spinner, spinnerVariants }
export default Spinner
