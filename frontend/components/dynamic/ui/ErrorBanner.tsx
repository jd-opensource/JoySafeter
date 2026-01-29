/**
 * ErrorBanner component
 * Displays error messages
 */

import React from 'react';

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({
  message,
  onRetry,
  onDismiss,
}) => {
  return (
    <div className="error-banner">
      <span>{message}</span>
      <div className="flex gap-2">
        {onRetry && <button onClick={onRetry}>Retry</button>}
        {onDismiss && <button onClick={onDismiss}>Dismiss</button>}
      </div>
    </div>
  );
};

ErrorBanner.displayName = 'ErrorBanner';
