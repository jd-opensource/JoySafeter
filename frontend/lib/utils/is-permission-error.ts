/**
 * Check if an error is a permission/authorization error
 */
export function isPermissionError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return (
    message.includes('403') ||
    message.includes('permission') ||
    message.includes('Forbidden') ||
    message.includes('insufficient') ||
    message.includes('Insufficient')
  )
}
