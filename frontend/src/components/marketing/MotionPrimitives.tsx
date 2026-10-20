'use client'

import { ReactNode, useSyncExternalStore } from 'react'
import { motion, useScroll, useTransform } from 'framer-motion'

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

function getReducedMotionSnapshot() {
  return typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia(REDUCED_MOTION_QUERY).matches
}

function getServerReducedMotionSnapshot() {
  // Keep server and initial hydration markup identical. The CSS media query
  // exposes motion wrappers until the browser preference snapshot is read.
  return false
}

function subscribeToReducedMotion(onChange: () => void) {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return () => {}
  }

  const query = window.matchMedia(REDUCED_MOTION_QUERY)
  if (typeof query.addEventListener === 'function') {
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }

  query.addListener(onChange)
  return () => query.removeListener(onChange)
}

function usePrefersReducedMotion() {
  return useSyncExternalStore(
    subscribeToReducedMotion,
    getReducedMotionSnapshot,
    getServerReducedMotionSnapshot,
  )
}

export function MotionReveal({
  children,
  delay = 0,
  y = 24,
  className,
}: {
  children: ReactNode
  delay?: number
  y?: number
  className?: string
}) {
  const prefersReducedMotion = usePrefersReducedMotion()
  return (
    <motion.div
      data-marketing-motion
      initial={prefersReducedMotion ? false : { opacity: 0, y }}
      animate={prefersReducedMotion ? { opacity: 1, y: 0 } : undefined}
      whileInView={prefersReducedMotion ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{ duration: prefersReducedMotion ? 0 : 0.62, delay: prefersReducedMotion ? 0 : delay, ease: [0.16, 1, 0.3, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

export function MotionStagger({ children, className }: { children: ReactNode; className?: string }) {
  const prefersReducedMotion = usePrefersReducedMotion()
  return (
    <motion.div
      data-marketing-motion
      initial={prefersReducedMotion ? false : 'hidden'}
      animate={prefersReducedMotion ? 'show' : undefined}
      whileInView={prefersReducedMotion ? undefined : 'show'}
      viewport={{ once: true, amount: 0.16 }}
      variants={{
        hidden: {},
        show: {
          transition: {
            staggerChildren: prefersReducedMotion ? 0 : 0.08,
          },
        },
      }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

export function MotionItem({ children, className }: { children: ReactNode; className?: string }) {
  const prefersReducedMotion = usePrefersReducedMotion()
  return (
    <motion.div
      data-marketing-motion
      animate={prefersReducedMotion ? { opacity: 1, y: 0, transition: { duration: 0 } } : undefined}
      variants={{
        hidden: { opacity: prefersReducedMotion ? 1 : 0, y: prefersReducedMotion ? 0 : 22 },
        show: { opacity: 1, y: 0, transition: { duration: prefersReducedMotion ? 0 : 0.55, ease: [0.16, 1, 0.3, 1] } },
      }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

export function ScrollDepth({ children, className }: { children?: ReactNode; className?: string }) {
  const prefersReducedMotion = usePrefersReducedMotion()
  const { scrollYProgress } = useScroll()
  const y = useTransform(scrollYProgress, [0, 1], [0, -120])
  const opacity = useTransform(scrollYProgress, [0, 0.4], [1, 0.86])

  return (
    <motion.div data-marketing-motion style={{ y: prefersReducedMotion ? 0 : y, opacity: prefersReducedMotion ? 1 : opacity }} className={className}>
      {children}
    </motion.div>
  )
}
