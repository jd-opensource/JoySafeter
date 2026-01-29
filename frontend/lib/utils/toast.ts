/**
 * Global Toast utility functions
 * Used to display error, success, warning, and info messages anywhere in the application
 */

import { toast as showToast } from '@/components/ui/use-toast'

/**
 * Display error toast
 * @param message Error message
 * @param title Optional title
 */
export function toastError(message: string, title?: string) {
  showToast({
    variant: 'destructive',
    title: title || 'Error',
    description: message,
    duration: 5000,
  })
}

/**
 * Display success toast
 * @param message Success message
 * @param title Optional title
 */
export function toastSuccess(message: string, title?: string) {
  showToast({
    variant: 'success',
    title: title || 'Success',
    description: message,
    duration: 3000,
  })
}

/**
 * Display warning toast
 * @param message Warning message
 * @param title Optional title
 */
export function toastWarning(message: string, title?: string) {
  showToast({
    variant: 'warning',
    title: title || 'Warning',
    description: message,
    duration: 4000,
  })
}

/**
 * Display info toast
 * @param message Info message
 * @param title Optional title
 */
export function toastInfo(message: string, title?: string) {
  showToast({
    variant: 'info',
    title: title || 'Info',
    description: message,
    duration: 3000,
  })
}

/**
 * Display default toast
 * @param message Message
 * @param title Optional title
 */
export function toast(message: string, title?: string) {
  showToast({
    variant: 'default',
    title: title,
    description: message,
    duration: 3000,
  })
}

/**
 * Unified error handling function
 * Automatically extracts error message from Error object and displays it
 * @param error Error object or error message string
 * @param defaultMessage Default error message (used when unable to extract from error)
 */
export function handleError(error: unknown, defaultMessage = 'Operation failed, please try again later') {
  let message = defaultMessage

  if (error instanceof Error) {
    message = error.message || defaultMessage
  } else if (typeof error === 'string') {
    message = error
  }

  toastError(message)
}
