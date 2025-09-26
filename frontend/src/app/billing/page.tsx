'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { ArrowLeft, CreditCard, Sparkles, Crown, Zap, Shield } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import PricingCard from '@/components/billing/PricingCard'
import SubscriptionManager from '@/components/billing/SubscriptionManager'

const fadeInUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5 }
}

interface PricingPlan {
  id: string
  name: string
  price: number
  currency: string
  interval: string
  features: {
    compilations: number | string
    optimizations: number | string
    historyRetention: number
    prioritySupport: boolean
    apiAccess: boolean
    customModels?: boolean
  }
}

export default function BillingPage() {
  const [plans, setPlans] = useState<Record<string, PricingPlan>>({})
  const [isLoading, setIsLoading] = useState(true)
  const [selectedPlan, setSelectedPlan] = useState<string | null>(null)
  const [showPricing, setShowPricing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchPlans()
  }, [])

  const fetchPlans = async () => {
    try {
      setIsLoading(true)
      const response = await fetch('/api/subscription/plans')
      
      if (response.ok) {
        const data = await response.json()
        setPlans(data.plans)
      } else {
        throw new Error('Failed to fetch plans')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load plans')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSelectPlan = async (planId: string) => {
    if (planId === 'free') {
      alert('You are already on the free plan!')
      return
    }

    setSelectedPlan(planId)
    
    try {
      // For demo purposes, we'll use dummy customer data
      const response = await fetch('/api/subscription/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          planId,
          customerEmail: 'demo@latexy.com',
          customerName: 'Demo User'
        })
      })

      const result = await response.json()
      
      if (result.success) {
        if (result.shortUrl) {
          // Open Razorpay payment page
          window.open(result.shortUrl, '_blank')
        } else {
          alert('Subscription created successfully!')
        }
      } else {
        alert(`Error: ${result.error || 'Failed to create subscription'}`)
      }
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Failed to create subscription'}`)
    } finally {
      setSelectedPlan(null)
    }
  }

  const handleShowPricing = () => {
    setShowPricing(true)
  }

  const handleBackToSubscription = () => {
    setShowPricing(false)
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 py-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-500 mx-auto"></div>
            <p className="mt-4 text-gray-600">Loading billing information...</p>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 py-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center">
            <div className="text-red-600 mb-4">
              <CreditCard className="w-12 h-12 mx-auto mb-2" />
              <h2 className="text-xl font-semibold">Error Loading Billing</h2>
            </div>
            <p className="text-gray-600 mb-6">{error}</p>
            <button
              onClick={fetchPlans}
              className="bg-primary-500 text-white px-6 py-3 rounded-lg hover:bg-primary-600 transition-colors"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 dark:from-slate-900 dark:to-slate-800">
      {/* Header */}
      <div className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-b border-gray-200 dark:border-gray-700 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <Link 
              href="/"
              className="flex items-center space-x-2 text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Back to Home</span>
            </Link>
            <div className="flex items-center space-x-2">
              <div className="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <span className="text-xl font-bold text-gray-900 dark:text-white">Latexy</span>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Header */}
        <motion.div 
          className="text-center mb-12"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <Badge variant="outline" className="mb-4 border-blue-500/50 text-blue-600 dark:text-blue-400">
            <Crown className="w-3 h-3 mr-1" />
            {showPricing ? 'Pricing Plans' : 'Billing Management'}
          </Badge>
          
          <h1 className="text-4xl md:text-5xl font-bold text-gray-900 dark:text-white mb-6">
            {showPricing ? 'Choose Your Plan' : 'Billing & Subscription'}
          </h1>
          <p className="text-xl text-gray-600 dark:text-gray-300 max-w-3xl mx-auto">
            {showPricing 
              ? 'Select the perfect plan for your resume optimization needs'
              : 'Manage your subscription and billing preferences'
            }
          </p>
        </motion.div>

        {showPricing ? (
          <>
            {/* Back Button */}
            <motion.div 
              className="mb-8"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5 }}
            >
              <Button
                variant="ghost"
                onClick={handleBackToSubscription}
                className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back to Subscription
              </Button>
            </motion.div>

            {/* Pricing Cards */}
            <motion.div 
              className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8"
              initial={{ opacity: 0, y: 40 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.2 }}
            >
              {Object.entries(plans).map(([planId, plan], index) => (
                <motion.div
                  key={planId}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: index * 0.1 }}
                >
                  <PricingCard
                    plan={{ ...plan, id: planId }}
                    isPopular={planId === 'pro'}
                    onSelectPlan={handleSelectPlan}
                    isLoading={selectedPlan === planId}
                  />
                </motion.div>
              ))}
            </motion.div>

            {/* Features Comparison */}
            <div className="mt-16">
              <h2 className="text-2xl font-bold text-gray-900 text-center mb-8">
                Feature Comparison
              </h2>
              <div className="bg-white rounded-lg shadow-md overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Feature
                        </th>
                        {Object.entries(plans).map(([planId, plan]) => (
                          <th key={planId} className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                            {plan.name}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      <tr>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          LaTeX Compilations
                        </td>
                        {Object.values(plans).map((plan, index) => (
                          <td key={index} className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-center">
                            {plan.features.compilations === 'unlimited' ? 'Unlimited' : plan.features.compilations}
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          AI Optimizations
                        </td>
                        {Object.values(plans).map((plan, index) => (
                          <td key={index} className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-center">
                            {plan.features.optimizations === 'unlimited' ? 'Unlimited' : plan.features.optimizations}
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          History Retention
                        </td>
                        {Object.values(plans).map((plan, index) => (
                          <td key={index} className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-center">
                            {plan.features.historyRetention === 0 ? 'None' : `${plan.features.historyRetention} days`}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </>
        ) : (
          /* Subscription Manager */
          <div className="max-w-2xl mx-auto">
            <SubscriptionManager onUpgrade={handleShowPricing} />
          </div>
        )}
      </div>
    </div>
  )
}
