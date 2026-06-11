'use client'

import React, { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import { AppErrorStateView } from '@/components/shared/app-error-state'
import { i18n } from '@/lib/i18n'
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
      const t = i18n.t.bind(i18n)

      return (
        <AppErrorStateView
          title={t('common.pageErrorTitle')}
          description={t('common.pageErrorDescription')}
          onRetry={this.handleReset}
          retryLabel={t('common.retry')}
        />
      )
    }

    return this.props.children
  }
}
