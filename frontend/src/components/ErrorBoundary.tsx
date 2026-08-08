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
        <div className="min-h-screen flex items-center justify-center bg-bg">
          <div className="max-w-md w-full mx-4">
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface">
              <div className="text-center p-8">
                <AlertTriangle className="w-12 h-12 text-warn mx-auto mb-4" />
                <h2 className="text-lg font-semibold text-fg mb-2">
                  Something went wrong
                </h2>
                <p className="text-fg-2 mb-6">
                  We encountered an unexpected error. Please try refreshing the page.
                </p>
                <button
                  onClick={() => window.location.reload()}
                  className="rounded-[var(--radius-md)] bg-accent px-4 py-2 flex items-center gap-2 mx-auto font-semibold text-accent-fg transition hover:brightness-110"
                >
                  <RefreshCw size={16} />
                  Refresh Page
                </button>

                {process.env.NODE_ENV === 'development' && this.state.error && (
                  <details className="mt-6 text-left">
                    <summary className="cursor-pointer text-sm text-fg-3 hover:text-fg-2">
                      Error Details (Development)
                    </summary>
                    <pre className="mt-2 p-3 bg-surface-2 rounded-[var(--radius-md)] text-xs text-fg-2 overflow-auto">
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