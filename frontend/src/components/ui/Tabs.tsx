'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Accessible compound Tabs primitive.
 *
 * Composition:
 *   <Tabs defaultValue="a"> or <Tabs value onValueChange>
 *     <TabsList>
 *       <TabsTrigger value="a" label="A" />
 *       <TabsTrigger value="b" label="B" />
 *     </TabsList>
 *     <TabsContent value="a">…</TabsContent>
 *     <TabsContent value="b">…</TabsContent>
 *   </Tabs>
 *
 * Implements the WAI-ARIA Tabs pattern: role=tablist/tab/tabpanel,
 * aria-selected/controls/labelledby, and ArrowLeft/Right + Home/End
 * roving-focus keyboard navigation. Works controlled or uncontrolled.
 */

interface TabsContextValue {
  /** Currently selected tab value. */
  value: string
  /** Select a tab value. */
  setValue: (value: string) => void
  /** Stable base id used to derive tab/panel ids. */
  baseId: string
  /** Register a trigger's value + ref for keyboard navigation. */
  register: (value: string, node: HTMLButtonElement | null) => void
}

const TabsContext = React.createContext<TabsContextValue | null>(null)

function useTabsContext(component: string): TabsContextValue {
  const ctx = React.useContext(TabsContext)
  if (!ctx) {
    throw new Error(`${component} must be used within <Tabs>`)
  }
  return ctx
}

/**
 * Recursively find the value of the first TabsTrigger in a tree so an
 * uncontrolled Tabs with no defaultValue still has a selected tab. Without
 * this, roving tabindex leaves every trigger at tabIndex -1, making the
 * tablist unreachable by keyboard and rendering no panel.
 */
function findFirstTabValue(children: React.ReactNode): string | undefined {
  let found: string | undefined
  React.Children.forEach(children, (child) => {
    if (found !== undefined || !React.isValidElement(child)) return
    if (child.type === TabsTrigger) {
      const val = (child.props as TabsTriggerProps).value
      if (typeof val === 'string') found = val
      return
    }
    const nested = (child.props as { children?: React.ReactNode }).children
    if (nested !== undefined) {
      found = findFirstTabValue(nested)
    }
  })
  return found
}

export interface TabsProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  /** Controlled selected value. */
  value?: string
  /** Uncontrolled initial value. */
  defaultValue?: string
  /** Called when the selected value changes. */
  onValueChange?: (value: string) => void
}

const Tabs = React.forwardRef<HTMLDivElement, TabsProps>(
  (
    { value, defaultValue, onValueChange, className, children, id, ...props },
    ref,
  ) => {
    const generatedId = React.useId()
    const baseId = id ?? generatedId

    const isControlled = value !== undefined
    const [internalValue, setInternalValue] = React.useState<string>(
      () => defaultValue ?? findFirstTabValue(children) ?? '',
    )
    const selected = isControlled ? (value as string) : internalValue

    // Ordered map of value -> trigger node, used for roving keyboard focus.
    const triggersRef = React.useRef<Map<string, HTMLButtonElement | null>>(
      new Map(),
    )

    const register = React.useCallback(
      (val: string, node: HTMLButtonElement | null) => {
        if (node) {
          triggersRef.current.set(val, node)
        } else {
          triggersRef.current.delete(val)
        }
      },
      [],
    )

    const setValue = React.useCallback(
      (next: string) => {
        if (!isControlled) {
          setInternalValue(next)
        }
        onValueChange?.(next)
      },
      [isControlled, onValueChange],
    )

    const contextValue = React.useMemo<TabsContextValue>(
      () => ({ value: selected, setValue, baseId, register }),
      [selected, setValue, baseId, register],
    )

    return (
      <TabsContext.Provider value={contextValue}>
        <div ref={ref} className={cn('flex flex-col', className)} {...props}>
          {children}
        </div>
      </TabsContext.Provider>
    )
  },
)
Tabs.displayName = 'Tabs'

export interface TabsListProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Accessible label for the tablist when no visible label exists. */
  'aria-label'?: string
}

const TabsList = React.forwardRef<HTMLDivElement, TabsListProps>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        role="tablist"
        className={cn(
          'flex items-stretch gap-1 border-b border-line',
          className,
        )}
        {...props}
      />
    )
  },
)
TabsList.displayName = 'TabsList'

export interface TabsTriggerProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'value'> {
  /** Value that links this trigger to its TabsContent panel. */
  value: string
  /** Visible label; may be overridden by children. */
  label?: React.ReactNode
}

const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ value, label, className, children, disabled, onKeyDown, ...props }, ref) => {
    const { value: selected, setValue, baseId, register } = useTabsContext(
      'TabsTrigger',
    )
    const isSelected = selected === value

    const innerRef = React.useRef<HTMLButtonElement | null>(null)
    const setRefs = React.useCallback(
      (node: HTMLButtonElement | null) => {
        innerRef.current = node
        register(value, node)
        if (typeof ref === 'function') {
          ref(node)
        } else if (ref) {
          ;(ref as React.MutableRefObject<HTMLButtonElement | null>).current =
            node
        }
      },
      [ref, register, value],
    )

    const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
      onKeyDown?.(event)
      if (event.defaultPrevented) return

      const list = innerRef.current?.closest('[role="tablist"]')
      if (!list) return

      const tabs = Array.from(
        list.querySelectorAll<HTMLButtonElement>(
          '[role="tab"]:not([disabled])',
        ),
      )
      const currentIndex = tabs.indexOf(innerRef.current as HTMLButtonElement)
      if (currentIndex === -1) return

      let nextIndex: number | null = null
      switch (event.key) {
        case 'ArrowRight':
          nextIndex = (currentIndex + 1) % tabs.length
          break
        case 'ArrowLeft':
          nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
          break
        case 'Home':
          nextIndex = 0
          break
        case 'End':
          nextIndex = tabs.length - 1
          break
        default:
          return
      }

      event.preventDefault()
      const nextTab = tabs[nextIndex]
      nextTab?.focus()
      nextTab?.click()
    }

    return (
      <button
        ref={setRefs}
        type="button"
        role="tab"
        id={`${baseId}-tab-${value}`}
        aria-selected={isSelected}
        aria-controls={`${baseId}-panel-${value}`}
        tabIndex={isSelected ? 0 : -1}
        disabled={disabled}
        onClick={() => setValue(value)}
        onKeyDown={handleKeyDown}
        className={cn(
          'inline-flex min-h-[44px] items-center justify-center whitespace-nowrap border-b-2 px-4 py-2 font-ui text-sm transition duration-150 motion-reduce:transition-none',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
          'disabled:pointer-events-none disabled:opacity-50',
          isSelected
            ? 'border-accent text-fg'
            : 'border-transparent text-fg-3 hover:text-fg-2',
          className,
        )}
        {...props}
      >
        {children ?? label}
      </button>
    )
  },
)
TabsTrigger.displayName = 'TabsTrigger'

export interface TabsContentProps
  extends React.HTMLAttributes<HTMLDivElement> {
  /** Value linking this panel to its TabsTrigger. */
  value: string
}

const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  ({ value, className, children, ...props }, ref) => {
    const { value: selected, baseId } = useTabsContext('TabsContent')
    const isSelected = selected === value

    return (
      <div
        ref={ref}
        role="tabpanel"
        id={`${baseId}-panel-${value}`}
        aria-labelledby={`${baseId}-tab-${value}`}
        hidden={!isSelected}
        tabIndex={0}
        className={cn(
          'font-body text-fg outline-none',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
          className,
        )}
        {...props}
      >
        {isSelected ? children : null}
      </div>
    )
  },
)
TabsContent.displayName = 'TabsContent'

export { Tabs, TabsList, TabsTrigger, TabsContent }
export default Tabs
