'use client'

import { ReactNode } from 'react'
import { motion, useReducedMotion, useScroll, useTransform } from 'framer-motion'

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
  const prefersReducedMotion = useReducedMotion()
  if (prefersReducedMotion) return <div className={className}>{children}</div>

  return (
    <motion.div
      data-marketing-motion
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{ duration: 0.62, delay, ease: [0.16, 1, 0.3, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

export function MotionStagger({ children, className }: { children: ReactNode; className?: string }) {
  const prefersReducedMotion = useReducedMotion()
  if (prefersReducedMotion) return <div className={className}>{children}</div>

  return (
    <motion.div
      data-marketing-motion
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.16 }}
      variants={{
        hidden: {},
        show: {
          transition: {
            staggerChildren: 0.08,
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
  const prefersReducedMotion = useReducedMotion()
  if (prefersReducedMotion) return <div className={className}>{children}</div>

  return (
    <motion.div
      data-marketing-motion
      variants={{
        hidden: { opacity: 0, y: 22 },
        show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.16, 1, 0.3, 1] } },
      }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

function AnimatedScrollDepth({ children, className }: { children?: ReactNode; className?: string }) {
  const { scrollYProgress } = useScroll()
  const y = useTransform(scrollYProgress, [0, 1], [0, -120])
  const opacity = useTransform(scrollYProgress, [0, 0.4], [1, 0.86])

  return (
    <motion.div data-marketing-motion style={{ y, opacity }} className={className}>
      {children}
    </motion.div>
  )
}

export function ScrollDepth({ children, className }: { children?: ReactNode; className?: string }) {
  const prefersReducedMotion = useReducedMotion()
  if (prefersReducedMotion) return <div className={className}>{children}</div>
  return <AnimatedScrollDepth className={className}>{children}</AnimatedScrollDepth>
}
