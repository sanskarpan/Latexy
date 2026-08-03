import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/**
 * Token-bound Button (redesign, PRD 2026-08-03). Styles resolve across all four
 * theme variants via semantic tokens. Legacy variant/size keys (default/outline/
 * ghost/secondary/destructive/link, sm/lg/xl/icon) are preserved so existing
 * call-sites keep working.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap font-ui text-sm font-medium rounded-[var(--radius-md)] transition duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-accent text-accent-fg hover:brightness-110",
        primary: "bg-accent text-accent-fg hover:brightness-110",
        destructive: "bg-err text-white hover:brightness-110",
        outline: "border border-line bg-transparent text-fg hover:bg-surface-2 hover:border-line-2",
        secondary: "bg-surface-2 text-fg hover:brightness-95",
        subtle: "bg-surface-2 text-fg-2 hover:text-fg",
        ghost: "text-fg hover:bg-surface-2",
        link: "text-accent-strong underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-[var(--radius-sm)] px-3",
        lg: "h-11 px-8",
        xl: "h-12 rounded-[var(--radius-lg)] px-10 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  loading?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? (
          <span className="flex items-center gap-2">
            <span
              className="h-4 w-4 animate-spin rounded-[var(--radius-pill)] border-2 border-current border-t-transparent motion-reduce:animate-none"
              aria-hidden="true"
            />
            <span>Loading…</span>
          </span>
        ) : (
          children
        )}
      </Comp>
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
export default Button
