import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Split a combined model id "provider:model_name" into [provider, model_name].
 * Only splits on the FIRST colon so Ollama-style names like "ollama:qwen3.5:latest"
 * correctly yield ["ollama", "qwen3.5:latest"].
 */
export function splitModelId(id: string): [string, string] {
  const idx = id.indexOf(':')
  if (idx === -1) return ['', id]
  return [id.slice(0, idx), id.slice(idx + 1)]
}
