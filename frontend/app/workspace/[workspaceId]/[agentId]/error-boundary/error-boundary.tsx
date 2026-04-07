'use client'

import React, { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import { createLogger } from '@/lib/logs/console/logger'

const logger = createLogger('ErrorBoundary')

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

/**
 * Error boundary component to catch JavaScript errors in child components.
 * Displays a fallback UI when an error occurs.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    logger.error('Error caught by boundary:', { error, errorInfo })
  }

  /**
   * Reset error state
   */
  handleReset = (): void => {
    this.setState({ hasError: false, error: null })
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-[16px] p-[24px]">
          <div className="text-center">
            <h2 className="mb-[8px] text-md-app font-semibold text-[var(--text-primary)]">
              Something went wrong
            </h2>
            <p className="text-small text-[var(--text-tertiary)]">
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
          </div>
          <button
            onClick={this.handleReset}
            className="rounded-md bg-[var(--surface-9)] px-[16px] py-[8px] text-small text-[var(--text-primary)] hover:bg-[var(--surface-10)]"
          >
            Try again
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
