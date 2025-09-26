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
    <div className="min-h-screen bg-gray-50 py-12">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="text-center mb-12">
          <Link 
            href="/"
            className="inline-flex items-center text-primary-600 hover:text-primary-700 mb-6"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Editor
          </Link>
          
          <h1 className="text-4xl font-bold text-gray-900 mb-4">
            {showPricing ? 'Choose Your Plan' : 'Billing & Subscription'}
          </h1>
          <p className="text-xl text-gray-600 max-w-3xl mx-auto">
            {showPricing 
              ? 'Select the perfect plan for your resume optimization needs'
              : 'Manage your subscription and billing preferences'
            }
          </p>
        </div>

        {showPricing ? (
          <>
            {/* Back Button */}
            <div className="mb-8">
              <button
                onClick={handleBackToSubscription}
                className="inline-flex items-center text-primary-600 hover:text-primary-700"
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back to Subscription
              </button>
            </div>

            {/* Pricing Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
              {Object.entries(plans).map(([planId, plan]) => (
                <PricingCard
                  key={planId}
                  plan={{ ...plan, id: planId }}
                  isPopular={planId === 'pro'}
                  onSelectPlan={handleSelectPlan}
                  isLoading={selectedPlan === planId}
                />
              ))}
            </div>

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
