'use client'

import { useState } from 'react'
import { Check, X } from 'lucide-react'

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

interface PricingCardProps {
  plan: PricingPlan
  isPopular?: boolean
  onSelectPlan: (planId: string) => void
  isLoading?: boolean
}

export default function PricingCard({ 
  plan, 
  isPopular = false, 
  onSelectPlan, 
  isLoading = false 
}: PricingCardProps) {
  const [isHovered, setIsHovered] = useState(false)

  const formatPrice = (price: number) => {
    if (price === 0) return 'Free'
    return `₹${(price / 100).toFixed(0)}`
  }

  const formatFeatureValue = (value: number | string) => {
    if (value === 'unlimited') return 'Unlimited'
    if (typeof value === 'number' && value === 0) return 'None'
    return value.toString()
  }

  return (
    <div
      className={`relative rounded-2xl border-2 p-8 transition-all duration-300 ${
        isPopular
          ? 'border-primary-500 bg-primary-50 shadow-lg scale-105'
          : 'border-gray-200 bg-white hover:border-primary-300 hover:shadow-md'
      } ${isHovered ? 'transform -translate-y-1' : ''}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {isPopular && (
        <div className="absolute -top-4 left-1/2 transform -translate-x-1/2">
          <span className="bg-primary-500 text-white px-4 py-1 rounded-full text-sm font-medium">
            Most Popular
          </span>
        </div>
      )}

      <div className="text-center mb-8">
        <h3 className="text-2xl font-bold text-gray-900 mb-2">{plan.name}</h3>
        <div className="mb-4">
          <span className="text-4xl font-bold text-gray-900">
            {formatPrice(plan.price)}
          </span>
          {plan.price > 0 && (
            <span className="text-gray-500 ml-2">/{plan.interval}</span>
          )}
        </div>
        <p className="text-gray-600 text-sm">
          {plan.id === 'free' && 'Perfect for trying out Latexy'}
          {plan.id === 'basic' && 'Great for individual job seekers'}
          {plan.id === 'pro' && 'Best for frequent users'}
          {plan.id === 'byok' && 'Use your own AI models'}
        </p>
      </div>

      <div className="space-y-4 mb-8">
        <div className="flex items-center justify-between">
          <span className="text-gray-600">LaTeX Compilations</span>
          <span className="font-semibold text-gray-900">
            {formatFeatureValue(plan.features.compilations)}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-gray-600">AI Optimizations</span>
          <span className="font-semibold text-gray-900">
            {formatFeatureValue(plan.features.optimizations)}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-gray-600">History Retention</span>
          <span className="font-semibold text-gray-900">
            {plan.features.historyRetention === 0 
              ? 'None' 
              : `${plan.features.historyRetention} days`}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-gray-600">Priority Support</span>
          {plan.features.prioritySupport ? (
            <Check className="w-5 h-5 text-green-500" />
          ) : (
            <X className="w-5 h-5 text-gray-400" />
          )}
        </div>

        <div className="flex items-center justify-between">
          <span className="text-gray-600">API Access</span>
          {plan.features.apiAccess ? (
            <Check className="w-5 h-5 text-green-500" />
          ) : (
            <X className="w-5 h-5 text-gray-400" />
          )}
        </div>

        {plan.features.customModels && (
          <div className="flex items-center justify-between">
            <span className="text-gray-600">Custom AI Models</span>
            <Check className="w-5 h-5 text-green-500" />
          </div>
        )}
      </div>

      <button
        onClick={() => onSelectPlan(plan.id)}
        disabled={isLoading}
        className={`w-full py-3 px-6 rounded-lg font-semibold transition-colors duration-200 ${
          isPopular
            ? 'bg-primary-500 text-white hover:bg-primary-600 disabled:bg-primary-300'
            : 'bg-gray-900 text-white hover:bg-gray-800 disabled:bg-gray-400'
        } disabled:cursor-not-allowed`}
      >
        {isLoading ? (
          <div className="flex items-center justify-center">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
            <span className="ml-2">Processing...</span>
          </div>
        ) : plan.id === 'free' ? (
          'Get Started Free'
        ) : (
          'Subscribe Now'
        )}
      </button>

      {plan.id === 'free' && (
        <p className="text-xs text-gray-500 text-center mt-3">
          No credit card required
        </p>
      )}
    </div>
  )
}
