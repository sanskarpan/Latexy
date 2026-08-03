'use client'

import React, { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  FileText, 
  Zap, 
  Target, 
  CheckCircle, 
  ArrowRight, 
  ArrowLeft,
  Sparkles,
  Users,
  TrendingUp,
  Shield
} from 'lucide-react'

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

export default function OnboardingFlow({ 
  isOpen, 
  onComplete, 
  onSkip, 
  userType = 'new' 
}: OnboardingFlowProps) {
  const [currentStep, setCurrentStep] = useState(0)
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set())

  const steps: OnboardingStep[] = [
    {
      id: 'welcome',
      title: 'Welcome to Latexy!',
      description: 'Your AI-powered resume optimization platform',
      icon: <Sparkles className="w-8 h-8 text-accent-strong" />,
      content: (
        <div className="text-center space-y-6">
          <div className="w-24 h-24 mx-auto bg-gradient-to-br from-accent to-accent rounded-full flex items-center justify-center">
            <FileText className="w-12 h-12 text-white" />
          </div>
          <div>
            <h3 className="text-2xl font-bold text-fg mb-2">
              Welcome to Latexy!
            </h3>
            <p className="text-fg-2 text-lg">
              Create ATS-friendly resumes with LaTeX precision and AI optimization
            </p>
          </div>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div className="p-4 bg-accent-soft rounded-lg">
              <Users className="w-6 h-6 text-accent-strong mx-auto mb-2" />
              <p className="text-sm font-medium text-accent-strong">10,000+</p>
              <p className="text-xs text-accent-strong">Happy Users</p>
            </div>
            <div className="p-4 bg-green-50 rounded-lg">
              <TrendingUp className="w-6 h-6 text-green-500 mx-auto mb-2" />
              <p className="text-sm font-medium text-green-700">95%</p>
              <p className="text-xs text-green-600">ATS Pass Rate</p>
            </div>
            <div className="p-4 bg-purple-50 rounded-lg">
              <Shield className="w-6 h-6 text-purple-500 mx-auto mb-2" />
              <p className="text-sm font-medium text-purple-700">100%</p>
              <p className="text-xs text-purple-600">Secure & Private</p>
            </div>
          </div>
        </div>
      )
    },
    {
      id: 'how-it-works',
      title: 'How Latexy Works',
      description: 'Three simple steps to optimize your resume',
      icon: <Zap className="w-8 h-8 text-accent-strong" />,
      content: (
        <div className="space-y-6">
          <h3 className="text-xl font-bold text-fg text-center mb-6">
            Three Simple Steps
          </h3>
          <div className="space-y-4">
            <div className="flex items-start gap-4 p-4 bg-accent-soft rounded-lg">
              <div className="w-8 h-8 bg-accent-soft0 text-white rounded-full flex items-center justify-center font-bold text-sm">
                1
              </div>
              <div>
                <h4 className="font-semibold text-accent-strong">Upload or Create</h4>
                <p className="text-accent-strong text-sm">
                  Upload your existing resume or create one using our LaTeX editor
                </p>
              </div>
            </div>
            <div className="flex items-start gap-4 p-4 bg-green-50 rounded-lg">
              <div className="w-8 h-8 bg-green-500 text-white rounded-full flex items-center justify-center font-bold text-sm">
                2
              </div>
              <div>
                <h4 className="font-semibold text-green-900">AI Optimization</h4>
                <p className="text-green-700 text-sm">
                  Paste the job description and let AI optimize your resume for ATS compatibility
                </p>
              </div>
            </div>
            <div className="flex items-start gap-4 p-4 bg-purple-50 rounded-lg">
              <div className="w-8 h-8 bg-purple-500 text-white rounded-full flex items-center justify-center font-bold text-sm">
                3
              </div>
              <div>
                <h4 className="font-semibold text-purple-900">Download & Apply</h4>
                <p className="text-purple-700 text-sm">
                  Get your optimized PDF resume and start applying with confidence
                </p>
              </div>
            </div>
          </div>
        </div>
      )
    },
    {
      id: 'features',
      title: 'Key Features',
      description: 'Discover what makes Latexy powerful',
      icon: <Target className="w-8 h-8 text-accent-strong" />,
      content: (
        <div className="space-y-6">
          <h3 className="text-xl font-bold text-fg text-center mb-6">
            Powerful Features
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 border border-line rounded-lg hover:border-accent transition-colors">
              <FileText className="w-6 h-6 text-accent-strong mb-2" />
              <h4 className="font-semibold text-fg mb-1">LaTeX Editor</h4>
              <p className="text-sm text-fg-2">
                Professional typesetting with syntax highlighting
              </p>
            </div>
            <div className="p-4 border border-line rounded-lg hover:border-accent transition-colors">
              <Zap className="w-6 h-6 text-accent-strong mb-2" />
              <h4 className="font-semibold text-fg mb-1">AI Optimization</h4>
              <p className="text-sm text-fg-2">
                Smart content optimization for job descriptions
              </p>
            </div>
            <div className="p-4 border border-line rounded-lg hover:border-accent transition-colors">
              <Target className="w-6 h-6 text-accent-strong mb-2" />
              <h4 className="font-semibold text-fg mb-1">ATS Scoring</h4>
              <p className="text-sm text-fg-2">
                Real-time compatibility scoring and recommendations
              </p>
            </div>
            <div className="p-4 border border-line rounded-lg hover:border-accent transition-colors">
              <Shield className="w-6 h-6 text-accent-strong mb-2" />
              <h4 className="font-semibold text-fg mb-1">BYOK Support</h4>
              <p className="text-sm text-fg-2">
                Use your own API keys for cost-effective optimization
              </p>
            </div>
          </div>
        </div>
      )
    },
    {
      id: 'get-started',
      title: 'Ready to Get Started?',
      description: 'Choose your path and start optimizing',
      icon: <CheckCircle className="w-8 h-8 text-accent-strong" />,
      content: (
        <div className="text-center space-y-6">
          <div>
            <h3 className="text-xl font-bold text-fg mb-2">
              You're All Set!
            </h3>
            <p className="text-fg-2">
              Ready to create your first optimized resume?
            </p>
          </div>
          
          {userType === 'new' && (
            <div className="p-4 bg-accent-soft rounded-lg border border-accent">
              <h4 className="font-semibold text-accent-strong mb-2">Free Trial Available</h4>
              <p className="text-accent-strong text-sm mb-3">
                Try 3 resume compilations right now - no account, no credit card required!
              </p>
              <div className="flex items-center justify-center gap-2 text-accent-strong text-sm">
                <CheckCircle className="w-4 h-4" />
                <span>No registration needed for trial</span>
              </div>
            </div>
          )}
          
          {userType === 'trial_converted' && (
            <div className="p-4 bg-green-50 rounded-lg border border-green-200">
              <h4 className="font-semibold text-green-900 mb-2">Welcome to the Community!</h4>
              <p className="text-green-700 text-sm">
                Thanks for joining Latexy! Your free account includes 10 compilations per day and 3 AI optimizations per month.
              </p>
            </div>
          )}
          
          {userType === 'premium' && (
            <div className="p-4 bg-purple-50 rounded-lg border border-purple-200">
              <h4 className="font-semibold text-purple-900 mb-2">Premium Features Unlocked!</h4>
              <p className="text-purple-700 text-sm">
                Enjoy unlimited optimizations, priority support, and advanced features.
              </p>
            </div>
          )}
          
          <div className="space-y-3">
            <button
              onClick={onComplete}
              className="w-full rounded-[var(--radius-md)] bg-accent font-semibold text-accent-fg transition hover:brightness-110 py-3 text-base font-medium"
            >
              Start Creating My Resume
            </button>
            <button
              onClick={onSkip}
              className="w-full text-fg-2 hover:text-fg text-sm"
            >
              Skip tutorial and explore on my own
            </button>
          </div>
        </div>
      )
    }
  ]

  const nextStep = () => {
    if (currentStep < steps.length - 1) {
      setCompletedSteps(prev => new Set([...prev, currentStep]))
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.9 }}
        className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden"
      >
        {/* Header */}
        <div className="p-6 border-b border-line">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-fg">
                Getting Started
              </h2>
              <p className="text-sm text-fg-2">
                Step {currentStep + 1} of {steps.length}
              </p>
            </div>
            <button
              onClick={onSkip}
              className="text-fg-3 hover:text-fg-2 text-sm"
            >
              Skip
            </button>
          </div>
          
          {/* Progress Bar */}
          <div className="mt-4">
            <div className="flex gap-2">
              {steps.map((_, index) => (
                <button
                  key={index}
                  onClick={() => goToStep(index)}
                  className={`flex-1 h-2 rounded-full transition-colors ${
                    index <= currentStep
                      ? 'bg-accent'
                      : 'bg-surface-2'
                  }`}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 min-h-[400px] flex flex-col">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentStep}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.3 }}
              className="flex-1"
            >
              {steps[currentStep].content}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-line bg-surface-2">
          <div className="flex items-center justify-between">
            <button
              onClick={prevStep}
              disabled={currentStep === 0}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                currentStep === 0
                  ? 'text-fg-3 cursor-not-allowed'
                  : 'text-fg-2 hover:bg-surface-2'
              }`}
            >
              <ArrowLeft className="w-4 h-4" />
              Previous
            </button>
            
            <div className="flex items-center gap-2">
              {steps.map((_, index) => (
                <button
                  key={index}
                  onClick={() => goToStep(index)}
                  className={`w-2 h-2 rounded-full transition-colors ${
                    index === currentStep
                      ? 'bg-accent'
                      : index < currentStep
                      ? 'bg-accent-soft'
                      : 'bg-surface-2'
                  }`}
                />
              ))}
            </div>
            
            {currentStep < steps.length - 1 ? (
              <button
                onClick={nextStep}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent font-semibold text-accent-fg transition hover:brightness-110 px-4 py-2 text-sm font-medium"
              >
                Next
                <ArrowRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={onComplete}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent font-semibold text-accent-fg transition hover:brightness-110 px-4 py-2 text-sm font-medium"
              >
                Get Started
                <CheckCircle className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  )
}

// Hook for managing onboarding state
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
    resetOnboarding
  }
}

