import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const separatorVariants = cva('shrink-0 bg-line', {
  variants: {
    orientation: {
      horizontal: 'h-px w-full',
      vertical: 'h-full w-px',
    },
  },
  defaultVariants: {
    orientation: 'horizontal',
  },
})

export interface SeparatorProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof separatorVariants> {
  /**
   * When true, the separator is purely visual and is hidden from the
   * accessibility tree (no role / aria-orientation is emitted).
   */
  decorative?: boolean
}

/**
 * Separator — a thin divider drawn in the `border-line` color.
 *
 * Renders horizontally by default. When `decorative` is false (the default
 * for semantic use is to set it explicitly), it exposes `role="separator"`
 * and `aria-orientation` so assistive tech can announce the boundary; when
 * `decorative` is true it is removed from the a11y tree.
 */
const Separator = React.forwardRef<HTMLDivElement, SeparatorProps>(
  ({ className, orientation = 'horizontal', decorative = false, ...props }, ref) => {
    const semanticProps = decorative
      ? { role: 'none' as const }
      : { role: 'separator' as const, 'aria-orientation': orientation ?? 'horizontal' }

    return (
      <div
        ref={ref}
        {...semanticProps}
        className={cn(separatorVariants({ orientation }), className)}
        {...props}
      />
    )
  }
)
Separator.displayName = 'Separator'

export { Separator, separatorVariants }
export default Separator
