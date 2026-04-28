export function heatMapTextColor(p: {
  min?: number
  max: number
  value: number
}): string {
  const { min = 0, max, value } = p
  if (max === min) return ''
  const ratio = (value - min) / (max - min)
  if (ratio >= 0.75) return 'text-dark-red'
  if (ratio >= 0.5) return 'text-dark-yellow'
  return ''
}

export function formatIntervalSeconds(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(2)}s`
  if (seconds < 3600)
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

export function formatTokenCounts(
  input: number | null,
  output: number | null,
  total: number | null,
): string {
  if (total != null) return total.toLocaleString()
  const parts: string[] = []
  if (input != null) parts.push(`${input.toLocaleString()} in`)
  if (output != null) parts.push(`${output.toLocaleString()} out`)
  return parts.join(' / ') || '—'
}

export function usdFormatter(value: number): string {
  if (value === 0) return '$0'
  if (value < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}
