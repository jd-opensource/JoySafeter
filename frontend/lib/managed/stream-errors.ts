type Translator = (key: string, options?: Record<string, unknown>) => string

export type ManagedStreamErrorEvent = {
  message?: unknown
  code?: unknown
  status?: unknown
  source?: unknown
} & object

export function getManagedStreamErrorMessage(
  t: Translator,
  event: ManagedStreamErrorEvent,
  fallbackKey: string,
): string {
  const message =
    typeof event.message === 'string' && event.message.trim()
      ? event.message.trim()
      : t(fallbackKey)
  const code = typeof event.code === 'string' && event.code.trim() ? event.code.trim() : ''
  const status = typeof event.status === 'number' ? `HTTP ${event.status}` : ''
  const source = typeof event.source === 'string' && event.source.trim() ? event.source.trim() : ''
  const details = [code, status, source].filter(Boolean)

  return details.length > 0 ? `${message} (${details.join(', ')})` : message
}
