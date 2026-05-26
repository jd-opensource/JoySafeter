import { toast as showToast } from '@/hooks/use-toast'

export function getErrorMessage(err: unknown, fallback = 'Operation failed'): string {
  if (err instanceof Error) return err.message || fallback
  if (typeof err === 'string') return err
  return fallback
}

export function toastError(message: string, title?: string) {
  showToast({
    variant: 'destructive',
    title: title || 'Error',
    description: message,
    duration: 5000,
  })
}

export function toastSuccess(message: string, title?: string) {
  showToast({
    variant: 'success',
    title: title || 'Success',
    description: message,
    duration: 3000,
  })
}
