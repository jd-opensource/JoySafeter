'use client'

import React, { Component, ErrorInfo, ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { AppErrorStateView } from '@/components/shared/app-error-state'
import { ApiError } from '@/lib/api-client'
import { i18n } from '@/lib/i18n'

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

      const errorCode = this.state.error instanceof ApiError ? this.state.error.code : undefined
      const isNetworkError = errorCode === 'NETWORK_ERROR' || errorCode === 'REQUEST_TIMEOUT'
      const isWebSocketError =
        errorCode === 'WEBSOCKET_CONNECTION_FAILED' || errorCode === 'WEBSOCKET_UNAVAILABLE'
      const t = i18n.t.bind(i18n)
      const description = isNetworkError
        ? t('common.networkConnectionError')
        : isWebSocketError
          ? t('common.realtimeConnectionError')
          : t('common.pageErrorDescription')

      return (
        <div>
          <AppErrorStateView
            title={t('common.pageErrorTitle')}
            description={description}
            onRetry={this.handleReset}
            retryLabel={t('common.retry')}
          />
          <div className="flex gap-2">
            <Button onClick={() => window.location.reload()} variant="default" size="sm">
              {t('common.refreshPage')}
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
