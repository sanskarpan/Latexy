import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const panelVariants = cva(
  'rounded-[var(--radius-lg)] border transition duration-150 motion-reduce:transition-none',
  {
    variants: {
      variant: {
        default: 'bg-surface border-line',
        inset: 'bg-surface-2 border-line-2',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
)

export interface PanelProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof panelVariants> {
  /** Optional uppercase label rendered in the header row. */
  title?: string
  /** Optional node rendered on the right side of the header row. */
  header?: React.ReactNode
  /** Apply default padding to the body region. Defaults to true. */
  padded?: boolean
}

/**
 * Panel — a surface container for grouping app sections.
 *
 * Renders an optional header row (uppercase `font-ui` label + right-slot node)
 * separated from the body by a `border-line` divider. Use `variant="inset"` for
 * nested/recessed regions and `padded={false}` for edge-to-edge body content
 * (e.g. tables, editors).
 */
const Panel = React.forwardRef<HTMLDivElement, PanelProps>(
  (
    { className, variant, title, header, padded = true, children, ...props },
    ref
  ) => {
    const hasHeader = title != null || header != null

    return (
      <div
        ref={ref}
        className={cn(panelVariants({ variant }), className)}
        {...props}
      >
        {hasHeader && (
          <div className="flex min-h-11 items-center justify-between gap-3 border-b border-line px-4 py-2.5">
            {title != null ? (
              <h2 className="font-ui text-xs font-medium uppercase tracking-wide text-fg-3">
                {title}
              </h2>
            ) : (
              <span aria-hidden="true" />
            )}
            {header != null && (
              <div className="flex items-center gap-2">{header}</div>
            )}
          </div>
        )}
        <div className={cn(padded && 'p-4')}>{children}</div>
      </div>
    )
  }
)
Panel.displayName = 'Panel'

export { Panel, panelVariants }
export default Panel
