'use client'

import React from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

interface ErrorBoundaryProps {
  children: React.ReactNode
  fallback?: React.ReactNode
}

export default class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Error caught by boundary:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-blue-50">
          <div className="max-w-md w-full mx-4">
            <div className="card">
              <div className="card-content text-center py-8">
                <AlertTriangle className="w-12 h-12 text-amber-500 mx-auto mb-4" />
                <h2 className="text-lg font-semibold text-secondary-900 mb-2">
                  Something went wrong
                </h2>
                <p className="text-secondary-600 mb-6">
                  We encountered an unexpected error. Please try refreshing the page.
                </p>
                <button
                  onClick={() => window.location.reload()}
                  className="btn-primary px-4 py-2 flex items-center gap-2 mx-auto"
                >
                  <RefreshCw size={16} />
                  Refresh Page
                </button>
                
                {process.env.NODE_ENV === 'development' && this.state.error && (
                  <details className="mt-6 text-left">
                    <summary className="cursor-pointer text-sm text-secondary-500 hover:text-secondary-700">
                      Error Details (Development)
                    </summary>
                    <pre className="mt-2 p-3 bg-secondary-50 rounded text-xs text-secondary-700 overflow-auto">
                      {this.state.error.toString()}
                    </pre>
                  </details>
                )}
              </div>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}