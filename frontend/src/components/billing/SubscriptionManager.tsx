'use client'

import { useState, useEffect } from 'react'
import { CreditCard, Calendar, AlertCircle, CheckCircle } from 'lucide-react'

interface Subscription {
  userId: string
  planId: string
  planName: string
  status: string
  features: {
    compilations: number | string
    optimizations: number | string
    historyRetention: number
    prioritySupport: boolean
    apiAccess: boolean
    customModels?: boolean
  }
  subscriptionId?: string
  currentPeriodEnd?: string
}

interface SubscriptionManagerProps {
  onUpgrade: () => void
}

export default function SubscriptionManager({ onUpgrade }: SubscriptionManagerProps) {
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCancelling, setIsCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchSubscription()
  }, [])

  const fetchSubscription = async () => {
    try {
      setIsLoading(true)
      const response = await fetch('/api/subscription/current')
      
      if (response.ok) {
        const data = await response.json()
        setSubscription(data)
      } else if (response.status === 404) {
        // No subscription found - user is on free plan
        setSubscription(null)
      } else {
        throw new Error('Failed to fetch subscription')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load subscription')
    } finally {
      setIsLoading(false)
    }
  }

  const handleCancelSubscription = async () => {
    if (!subscription || !confirm('Are you sure you want to cancel your subscription?')) {
      return
    }

    try {
      setIsCancelling(true)
      const response = await fetch('/api/subscription/cancel', {
        method: 'POST',
      })

      if (response.ok) {
        const result = await response.json()
        if (result.success) {
          await fetchSubscription() // Refresh subscription data
          alert('Subscription cancelled successfully')
        } else {
          throw new Error(result.error || 'Failed to cancel subscription')
        }
      } else {
        throw new Error('Failed to cancel subscription')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel subscription')
    } finally {
      setIsCancelling(false)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active':
        return 'text-green-600 bg-green-100'
      case 'cancelled':
        return 'text-red-600 bg-red-100'
      case 'paused':
        return 'text-yellow-600 bg-yellow-100'
      default:
        return 'text-gray-600 bg-gray-100'
    }
  }

  const formatFeatureValue = (value: number | string) => {
    if (value === 'unlimited') return 'Unlimited'
    if (typeof value === 'number' && value === 0) return 'None'
    return value.toString()
  }

  if (isLoading) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="animate-pulse">
          <div className="h-4 bg-gray-200 rounded w-1/4 mb-4"></div>
          <div className="h-8 bg-gray-200 rounded w-1/2 mb-4"></div>
          <div className="space-y-3">
            <div className="h-4 bg-gray-200 rounded"></div>
            <div className="h-4 bg-gray-200 rounded w-3/4"></div>
            <div className="h-4 bg-gray-200 rounded w-1/2"></div>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="flex items-center text-red-600 mb-4">
          <AlertCircle className="w-5 h-5 mr-2" />
          <span className="font-medium">Error loading subscription</span>
        </div>
        <p className="text-gray-600 mb-4">{error}</p>
        <button
          onClick={fetchSubscription}
          className="bg-primary-500 text-white px-4 py-2 rounded-lg hover:bg-primary-600 transition-colors"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!subscription) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="text-center">
          <CreditCard className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 mb-2">No Active Subscription</h3>
          <p className="text-gray-600 mb-6">
            You're currently on the free plan. Upgrade to unlock more features.
          </p>
          <button
            onClick={onUpgrade}
            className="bg-primary-500 text-white px-6 py-3 rounded-lg hover:bg-primary-600 transition-colors"
          >
            View Plans
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-gray-900">Current Subscription</h3>
        <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(subscription.status)}`}>
          {subscription.status.charAt(0).toUpperCase() + subscription.status.slice(1)}
        </span>
      </div>

      <div className="mb-6">
        <h4 className="text-xl font-bold text-gray-900 mb-2">{subscription.planName}</h4>
        {subscription.currentPeriodEnd && (
          <div className="flex items-center text-gray-600 text-sm">
            <Calendar className="w-4 h-4 mr-2" />
            <span>
              Renews on {new Date(subscription.currentPeriodEnd).toLocaleDateString()}
            </span>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="bg-gray-50 p-4 rounded-lg">
          <div className="text-sm text-gray-600 mb-1">Compilations</div>
          <div className="text-lg font-semibold text-gray-900">
            {formatFeatureValue(subscription.features.compilations)}
          </div>
        </div>

        <div className="bg-gray-50 p-4 rounded-lg">
          <div className="text-sm text-gray-600 mb-1">Optimizations</div>
          <div className="text-lg font-semibold text-gray-900">
            {formatFeatureValue(subscription.features.optimizations)}
          </div>
        </div>

        <div className="bg-gray-50 p-4 rounded-lg">
          <div className="text-sm text-gray-600 mb-1">History Retention</div>
          <div className="text-lg font-semibold text-gray-900">
            {subscription.features.historyRetention === 0 
              ? 'None' 
              : `${subscription.features.historyRetention} days`}
          </div>
        </div>

        <div className="bg-gray-50 p-4 rounded-lg">
          <div className="text-sm text-gray-600 mb-1">Features</div>
          <div className="flex space-x-2">
            {subscription.features.prioritySupport && (
              <CheckCircle className="w-4 h-4 text-green-500" title="Priority Support" />
            )}
            {subscription.features.apiAccess && (
              <CheckCircle className="w-4 h-4 text-blue-500" title="API Access" />
            )}
            {subscription.features.customModels && (
              <CheckCircle className="w-4 h-4 text-purple-500" title="Custom Models" />
            )}
          </div>
        </div>
      </div>

      <div className="flex space-x-3">
        <button
          onClick={onUpgrade}
          className="flex-1 bg-primary-500 text-white py-2 px-4 rounded-lg hover:bg-primary-600 transition-colors"
        >
          Change Plan
        </button>
        
        {subscription.status === 'active' && subscription.subscriptionId && (
          <button
            onClick={handleCancelSubscription}
            disabled={isCancelling}
            className="flex-1 bg-red-500 text-white py-2 px-4 rounded-lg hover:bg-red-600 transition-colors disabled:bg-red-300 disabled:cursor-not-allowed"
          >
            {isCancelling ? 'Cancelling...' : 'Cancel'}
          </button>
        )}
      </div>
    </div>
  )
}
