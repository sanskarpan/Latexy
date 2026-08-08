import * as React from "react"

import { cn } from "@/lib/utils"

/** Token-bound Input (redesign, PRD 2026-08-03). */
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-10 w-full rounded-[var(--radius-md)] border border-line-2 bg-surface px-3 py-2 text-sm text-fg transition duration-150 motion-reduce:transition-none file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-fg-3 focus-visible:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
export default Input
