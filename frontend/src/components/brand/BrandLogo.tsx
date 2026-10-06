import type { SVGProps } from 'react'

export function BrandMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 96 96" fill="none" aria-hidden="true" {...props}>
      <path fill="currentColor" d="M16 13h29v14H30v42h44v14H16V13Zm39 0h25v37H66V27H55V13Z" />
    </svg>
  )
}

export function BrandLogo({ small = false }: { small?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5 whitespace-nowrap">
      <BrandMark className={small ? 'h-6 w-6 shrink-0' : 'h-7 w-7 shrink-0'} />
      <span className={small ? 'font-display text-lg font-semibold tracking-[-0.055em]' : 'font-display text-xl font-semibold tracking-[-0.055em]'}>
        Latexy
      </span>
    </span>
  )
}
