import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/**
 * Token-bound Badge (redesign, PRD 2026-08-03). Legacy variant keys
 * (default/secondary/destructive/outline/success/warning/info) preserved; the
 * status variants map onto the semantic ok/warn tokens.
 */
const badgeVariants = cva(
  "inline-flex items-center rounded-[var(--radius-sm)] border px-2 py-0.5 font-ui text-[0.7rem] font-semibold uppercase tracking-[var(--track-label)] transition duration-150 motion-reduce:transition-none focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
  {
    variants: {
      variant: {
        default: "border-transparent bg-accent text-accent-fg",
        accent: "border-accent bg-accent-soft text-accent-strong",
        secondary: "border-transparent bg-surface-2 text-fg-2",
        outline: "border-line text-fg-2",
        destructive: "border-transparent bg-err text-white",
        success: "border-[color-mix(in_srgb,var(--ok)_30%,transparent)] text-ok",
        ok: "border-[color-mix(in_srgb,var(--ok)_30%,transparent)] text-ok",
        warning: "border-[color-mix(in_srgb,var(--warn)_30%,transparent)] text-warn",
        warn: "border-[color-mix(in_srgb,var(--warn)_30%,transparent)] text-warn",
        info: "border-accent bg-accent-soft text-accent-strong",
      },
    },
    defaultVariants: { variant: "default" },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
export default Badge
