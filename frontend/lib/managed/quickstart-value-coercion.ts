export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function objectValue(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined
}
