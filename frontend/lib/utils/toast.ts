/**
 * Global Toast utility functions
 * Used to display error and success messages anywhere in the application
 */

import { toast as showToast } from '@/hooks/use-toast'

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
