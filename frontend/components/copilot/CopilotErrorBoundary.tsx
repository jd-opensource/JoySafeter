'use client'

import { AlertCircle } from 'lucide-react'
import React, { Component, ErrorInfo, ReactNode } from 'react'

import { Button } from '@/components/ui/button'

interface Props {
  children: ReactNode
  fallback?: ReactNode
  onError?: (error: Error, errorInfo: ErrorInfo) => void
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

export class CopilotErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[CopilotErrorBoundary] Error caught:', error, errorInfo)
    this.setState({ errorInfo })

    if (this.props.onError) {
      this.props.onError(error, errorInfo)
    }
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      const errorMessage = this.state.error?.message || 'An unexpected error occurred'
      const isNetworkError = errorMessage.includes('fetch') || errorMessage.includes('network')
      const isWebSocketError = errorMessage.includes('WebSocket') || errorMessage.includes('ws')

      return (
        <div className="flex min-h-[200px] flex-col items-center justify-center p-8 text-center">
          <AlertCircle className="mb-4 h-12 w-12 text-[var(--status-error)]" />
          <h3 className="mb-2 text-lg font-semibold text-[var(--text-primary)]">Something went wrong</h3>
          <p className="mb-4 max-w-md text-sm text-[var(--text-secondary)]">
            {isNetworkError
              ? 'Network connection error. Please check your internet connection and try again.'
              : isWebSocketError
                ? 'Connection error. Please refresh the page and try again.'
                : errorMessage}
          </p>
          <div className="flex gap-2">
            <Button onClick={this.handleReset} variant="outline" size="sm">
              Try Again
            </Button>
            <Button onClick={() => window.location.reload()} variant="default" size="sm">
              Refresh Page
            </Button>
          </div>
          {process.env.NODE_ENV === 'development' && this.state.errorInfo && (
            <details className="mt-4 max-w-2xl text-left">
              <summary className="mb-2 cursor-pointer text-xs text-[var(--text-tertiary)]">
                Error Details (Development Only)
              </summary>
              <pre className="max-h-64 overflow-auto rounded bg-[var(--surface-3)] p-4 text-xs">
                {this.state.error?.stack}
                {'\n\n'}
                {this.state.errorInfo.componentStack}
              </pre>
            </details>
          )}
        </div>
      )
    }

    return this.props.children
  }
}
