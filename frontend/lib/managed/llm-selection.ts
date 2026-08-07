import type { Secret } from '@/types/managed'

export function selectInitialSecret(options: Secret[]): string {
  if (options.length === 1) return options[0].name
  const defaults = options.filter((option) => option.is_default)
  return defaults.length === 1 ? defaults[0].name : ''
}
