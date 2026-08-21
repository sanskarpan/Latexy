'use client'

import React, { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import {
  FileText,
  Zap,
  Target,
  CheckCircle,
  ArrowRight,
  ArrowLeft,
  Sparkles,
  Shield,
  PenLine,
  LayoutTemplate,
  Upload,
} from 'lucide-react'
import { apiClient } from '@/lib/api-client'

interface OnboardingStep {
  id: string
  title: string
  description: string
  icon: React.ReactNode
  content: React.ReactNode
}

interface OnboardingFlowProps {
  isOpen: boolean
  onComplete: () => void
  onSkip: () => void
  userType?: 'new' | 'trial_converted' | 'premium'
}

/** Uppercase mono eyebrow label, matching the app's "LIBRARY"/"WORKSPACE" chrome. */
function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] font-mono uppercase tracking-[0.2em] text-fg-3">{children}</p>
  )
}

/** Small square icon tile — consistent accent treatment across every step. */
function IconTile({ icon, size = 'md' }: { icon: React.ReactNode; size?: 'md' | 'lg' }) {
  const box = size === 'lg' ? 'w-16 h-16' : 'w-10 h-10'
  return (
    <div
      className={`${box} shrink-0 grid place-items-center rounded-[var(--radius-md)] bg-accent-soft text-accent-strong`}
    >
      {icon}
    </div>
  )
}

/** Neutral bordered card — the single card style used everywhere (no colored fills). */
function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4 ${className}`}>
      {children}
    </div>
  )
}

export default function OnboardingFlow({
  isOpen,
  onComplete,
  onSkip,
  userType = 'new',
}: OnboardingFlowProps) {
  const [currentStep, setCurrentStep] = useState(0)
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set())
  const [freePlanCopy, setFreePlanCopy] = useState(
    'a generous daily compilation allowance and monthly AI optimizations',
  )

  // Free-plan limits drift as pricing changes — pull the real numbers from the
  // same /subscription/plans endpoint the billing page uses instead of hardcoding them.
  useEffect(() => {
    if (userType === 'premium') return
    let cancelled = false
    apiClient.getSubscriptionPlans().then((res) => {
      if (cancelled || !res.success || !res.data) return
      const free = res.data.plans?.free as { compilations?: number | string; optimizations?: number | string } | undefined
      if (free && typeof free.compilations !== 'undefined' && typeof free.optimizations !== 'undefined') {
        setFreePlanCopy(`${free.compilations} compilations a day and ${free.optimizations} AI optimizations a month`)
      }
    }).catch(() => { /* keep the non-numeric fallback copy */ })
    return () => { cancelled = true }
  }, [userType])

  const prefersReducedMotion = useReducedMotion()
  const panelRef = useRef<HTMLDivElement>(null)
  const previouslyFocusedRef = useRef<HTMLElement | null>(null)
  const titleId = 'onboarding-flow-title'

  // Focus management, focus trap, Escape-to-close, and body scroll lock.
  // Keyed on isOpen so it engages on open and cleans up fully on close.
  useEffect(() => {
    if (!isOpen) return

    // Remember what had focus so we can restore it when the modal closes.
    previouslyFocusedRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null

    // Lock body scroll while the modal is open. `overflow: hidden` alone
    // doesn't stop touch-driven rubber-band scrolling on mobile Safari — the
    // page can still bounce beneath the fixed backdrop, briefly exposing
    // unstyled page content past its edges (the "backdrop doesn't cover the
    // full viewport" symptom). Pairing it with `overscroll-behavior: none`
    // blocks that bounce/scroll-chaining outright.
    const previousOverflow = document.body.style.overflow
    const previousOverscroll = document.body.style.overscrollBehavior
    document.body.style.overflow = 'hidden'
    document.body.style.overscrollBehavior = 'none'

    const getFocusable = (): HTMLElement[] => {
      const panel = panelRef.current
      if (!panel) return []
      return Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
        )
      ).filter((el) => el.offsetParent !== null || el === document.activeElement)
    }

    // Move focus into the modal (first focusable, else the panel itself).
    const focusTarget = getFocusable()[0] ?? panelRef.current
    focusTarget?.focus()

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onSkip()
        return
      }
      if (e.key !== 'Tab') return

      const focusable = getFocusable()
      if (focusable.length === 0) {
        e.preventDefault()
        panelRef.current?.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement

      if (e.shiftKey) {
        if (active === first || !panelRef.current?.contains(active)) {
          e.preventDefault()
          last.focus()
        }
      } else if (active === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      document.body.style.overscrollBehavior = previousOverscroll
      previouslyFocusedRef.current?.focus?.()
    }
  }, [isOpen, onSkip])

  const steps: OnboardingStep[] = [
    {
      id: 'welcome',
      title: 'Welcome to Latexy',
      description: 'Your AI-powered resume optimization platform',
      icon: <Sparkles className="w-8 h-8 text-accent-strong" />,
      content: (
        <div className="space-y-6">
          <div className="flex flex-col items-center text-center space-y-4">
            <IconTile size="lg" icon={<FileText className="w-8 h-8" />} />
            <div className="space-y-1.5">
              <Eyebrow>Welcome</Eyebrow>
              <h3 className="text-2xl font-semibold text-fg">Résumés, typeset.</h3>
              <p className="text-fg-2 max-w-md">
                Latexy pairs LaTeX-grade typesetting with AI tailoring, so every resume you
                send is precise, ATS-ready, and matched to the role.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              { icon: <FileText className="w-5 h-5" />, label: 'Typeset in LaTeX', desc: 'Pixel-perfect, professional formatting.' },
              { icon: <Target className="w-5 h-5" />, label: 'ATS-aware', desc: 'See how trackers actually read your resume.' },
              { icon: <Sparkles className="w-5 h-5" />, label: 'AI tailoring', desc: 'Match any job description in seconds.' },
            ].map((f) => (
              <Card key={f.label} className="space-y-2">
                <span className="grid place-items-center w-8 h-8 rounded-[var(--radius-sm)] bg-accent-soft text-accent-strong">
                  {f.icon}
                </span>
                <p className="text-sm font-medium text-fg">{f.label}</p>
                <p className="text-xs text-fg-2 leading-relaxed">{f.desc}</p>
              </Card>
            ))}
          </div>
        </div>
      ),
    },
    {
      id: 'how-it-works',
      title: 'How Latexy works',
      description: 'Three simple steps to a tailored resume',
      icon: <Zap className="w-8 h-8 text-accent-strong" />,
      content: (
        <div className="space-y-5">
          <div className="text-center space-y-1.5">
            <Eyebrow>The workflow</Eyebrow>
            <h3 className="text-xl font-semibold text-fg">Three steps to a tailored resume</h3>
          </div>
          <div className="space-y-3">
            {[
              { n: 1, title: 'Start your resume', desc: 'Pick a template, import an existing file, or write LaTeX in the Studio.' },
              { n: 2, title: 'Tailor with AI', desc: 'Paste the job description — Latexy rewrites and optimizes for ATS in seconds.' },
              { n: 3, title: 'Compile & apply', desc: 'Get a clean, typeset PDF with a live ATS score, then send it out with confidence.' },
            ].map((s) => (
              <Card key={s.n} className="flex items-start gap-4">
                <span className="grid place-items-center w-8 h-8 shrink-0 rounded-[var(--radius-pill)] bg-accent text-accent-fg text-sm font-semibold">
                  {s.n}
                </span>
                <div className="space-y-0.5">
                  <h4 className="font-medium text-fg">{s.title}</h4>
                  <p className="text-sm text-fg-2 leading-relaxed">{s.desc}</p>
                </div>
              </Card>
            ))}
          </div>
        </div>
      ),
    },
    {
      id: 'features',
      title: 'What you get',
      description: 'The tools behind every Latexy resume',
      icon: <Target className="w-8 h-8 text-accent-strong" />,
      content: (
        <div className="space-y-5">
          <div className="text-center space-y-1.5">
            <Eyebrow>Toolkit</Eyebrow>
            <h3 className="text-xl font-semibold text-fg">Everything in one workspace</h3>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              { icon: <FileText className="w-5 h-5" />, title: 'LaTeX Studio', desc: 'Live editor with syntax highlighting and instant PDF preview.' },
              { icon: <Zap className="w-5 h-5" />, title: 'AI optimization', desc: 'Rewrites content to match a job — you review every change.' },
              { icon: <Target className="w-5 h-5" />, title: 'ATS scoring', desc: 'Real-time compatibility score with concrete fixes.' },
              { icon: <Shield className="w-5 h-5" />, title: 'Bring your own key', desc: 'Use your own model keys for cost-efficient runs.' },
            ].map((f) => (
              <Card key={f.title} className="flex items-start gap-3 transition-colors hover:border-accent">
                <IconTile icon={f.icon} />
                <div className="space-y-0.5">
                  <h4 className="font-medium text-fg">{f.title}</h4>
                  <p className="text-sm text-fg-2 leading-relaxed">{f.desc}</p>
                </div>
              </Card>
            ))}
          </div>
        </div>
      ),
    },
    {
      id: 'get-started',
      title: "You're all set",
      description: 'Pick how you want to start',
      icon: <CheckCircle className="w-8 h-8 text-accent-strong" />,
      content: (
        <div className="space-y-5">
          <div className="flex flex-col items-center text-center space-y-3">
            <IconTile size="lg" icon={<CheckCircle className="w-8 h-8" />} />
            <div className="space-y-1.5">
              <Eyebrow>Ready</Eyebrow>
              <h3 className="text-xl font-semibold text-fg">You&apos;re all set</h3>
              <p className="text-fg-2 max-w-md">
                {userType === 'premium'
                  ? 'Your plan includes unlimited compilations and AI optimizations. Pick a starting point below.'
                  : `Your free account includes ${freePlanCopy}. Pick a starting point below.`}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              { icon: <LayoutTemplate className="w-5 h-5" />, label: 'Use a template', desc: 'Start from 50+ curated designs.', href: '/templates' },
              { icon: <Upload className="w-5 h-5" />, label: 'Import a resume', desc: 'Bring a PDF, DOCX, or .tex file.', href: '/workspace/new' },
              { icon: <PenLine className="w-5 h-5" />, label: 'Write from scratch', desc: 'Open the LaTeX Studio.', href: '/try' },
            ].map((o) => (
              <Link
                key={o.label}
                href={o.href}
                onClick={onComplete}
                className="block space-y-2 rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4 transition hover:border-accent"
              >
                <span className="grid place-items-center w-8 h-8 rounded-[var(--radius-sm)] bg-accent-soft text-accent-strong">
                  {o.icon}
                </span>
                <p className="text-sm font-medium text-fg">{o.label}</p>
                <p className="text-xs text-fg-2 leading-relaxed">{o.desc}</p>
              </Link>
            ))}
          </div>

          <div className="space-y-2 pt-1">
            <button
              onClick={onComplete}
              className="w-full rounded-[var(--radius-md)] bg-accent py-3 text-base font-semibold text-accent-fg transition hover:brightness-110"
            >
              Create my first resume
            </button>
            <button
              onClick={onSkip}
              className="w-full py-1.5 text-sm text-fg-2 transition hover:text-fg"
            >
              Skip and explore on my own
            </button>
          </div>
        </div>
      ),
    },
  ]

  const nextStep = () => {
    if (currentStep < steps.length - 1) {
      setCompletedSteps((prev) => new Set([...prev, currentStep]))
      setCurrentStep(currentStep + 1)
    }
  }

  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1)
    }
  }

  const goToStep = (stepIndex: number) => {
    setCurrentStep(stepIndex)
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overscroll-contain bg-[var(--overlay)] p-4"
      onClick={onSkip}
    >
      <motion.div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        initial={prefersReducedMotion ? false : { opacity: 0, scale: 0.96, y: 8 }}
        animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
        exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: prefersReducedMotion ? 0 : 0.2, ease: 'easeOut' }}
        className="flex max-h-[90vh] supports-[height:100dvh]:max-h-[90dvh] w-full max-w-2xl flex-col overflow-hidden rounded-[var(--radius-xl,20px)] border border-line bg-surface shadow-2xl focus:outline-none"
      >
        {/* Header */}
        <div className="border-b border-line px-6 py-5">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Eyebrow>Getting started</Eyebrow>
              <h2 id={titleId} className="text-base font-semibold text-fg">
                {steps[currentStep].title}
              </h2>
            </div>
            <button
              onClick={onSkip}
              className="text-sm text-fg-3 transition hover:text-fg-2"
            >
              Skip
            </button>
          </div>

          {/* Segmented progress — each segment has a real touch target (min-h-11)
              with a thin visible bar centered inside it. */}
          <div className="mt-4 flex gap-1.5" role="group" aria-label="Onboarding progress">
            {steps.map((_, index) => (
              <button
                key={index}
                onClick={() => goToStep(index)}
                aria-label={`Go to step ${index + 1}`}
                aria-current={index === currentStep ? 'step' : undefined}
                className="flex min-h-[44px] flex-1 items-center rounded-[var(--radius-sm)] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <span
                  className={`h-1.5 w-full rounded-[var(--radius-pill)] transition-colors ${
                    index === currentStep
                      ? 'bg-accent'
                      : index < currentStep
                      ? 'bg-accent-strong'
                      : 'bg-surface-2'
                  }`}
                />
              </button>
            ))}
          </div>
        </div>

        {/* Content — `min-h-0` (not a fixed min-height) is required here: this
            flex item sits between a header and footer inside a `max-h` +
            `overflow-hidden` panel, so a rigid min-height can force the
            column past the panel's height budget on short mobile viewports.
            Once that happens the excess is clipped by the panel's
            `overflow-hidden` instead of being reachable via this element's
            own `overflow-y-auto`, which is how the last card in a step's
            grid can end up unreachable on mobile. */}
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-6 py-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentStep}
              initial={prefersReducedMotion ? false : { opacity: 0, x: 16 }}
              animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, x: 0 }}
              exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, x: -16 }}
              transition={{ duration: prefersReducedMotion ? 0 : 0.22 }}
              className="flex-1"
            >
              {steps[currentStep].content}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-line bg-surface-2 px-6 py-4">
          <button
            onClick={prevStep}
            disabled={currentStep === 0}
            className={`flex items-center gap-2 rounded-[var(--radius-md)] px-3 py-2 text-sm font-medium transition-colors ${
              currentStep === 0
                ? 'cursor-not-allowed text-fg-3'
                : 'text-fg-2 hover:bg-surface hover:text-fg'
            }`}
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>

          <p className="text-xs font-mono text-fg-3">
            {currentStep + 1} / {steps.length}
          </p>

          {currentStep < steps.length - 1 ? (
            <button
              onClick={nextStep}
              className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110"
            >
              Next
              <ArrowRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              onClick={onComplete}
              className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110"
            >
              Get started
              <CheckCircle className="h-4 w-4" />
            </button>
          )}
        </div>
      </motion.div>
    </div>
  )
}

// Hook for managing onboarding state.
//
// KNOWN GAP: completion is tracked in localStorage only, so it is device-local
// and re-triggers in every new browser/device the user signs into. A full fix
// needs a server-side `has_onboarded` flag (persisted via an API call and
// hydrated from the session) plus a UI entry point to replay it — both require
// backend + workspace/page.tsx changes outside this file's scope.
export function useOnboarding() {
  const [isOnboardingOpen, setIsOnboardingOpen] = useState(false)
  // Default to true (assume completed) until localStorage check resolves.
  // Prevents a flash where the onboarding modal briefly opens before
  // discovering that it was already completed in a prior session.
  const [hasCompletedOnboarding, setHasCompletedOnboarding] = useState(true)

  useEffect(() => {
    const completed = localStorage.getItem('latexy_onboarding_completed')
    setHasCompletedOnboarding(!!completed)
  }, [])

  const startOnboarding = () => {
    setIsOnboardingOpen(true)
  }

  const completeOnboarding = () => {
    setIsOnboardingOpen(false)
    setHasCompletedOnboarding(true)
    localStorage.setItem('latexy_onboarding_completed', 'true')
  }

  const skipOnboarding = () => {
    setIsOnboardingOpen(false)
    setHasCompletedOnboarding(true)
    localStorage.setItem('latexy_onboarding_completed', 'true')
  }

  const resetOnboarding = () => {
    setHasCompletedOnboarding(false)
    localStorage.removeItem('latexy_onboarding_completed')
  }

  return {
    isOnboardingOpen,
    hasCompletedOnboarding,
    startOnboarding,
    completeOnboarding,
    skipOnboarding,
    resetOnboarding,
  }
}
