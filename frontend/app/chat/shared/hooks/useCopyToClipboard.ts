'use client'

import { useState, useRef, useCallback } from 'react'

import { copyToClipboard } from '@/lib/utils/clipboard'

/**
 * Hook that encapsulates the copy-to-clipboard pattern with visual feedback.
 * Returns `copied` (true for 2s after a successful copy) and `handleCopy`.
 */
export function useCopyToClipboard() {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleCopy = useCallback(async (text: string) => {
    try {
      await copyToClipboard(text)
      if (timerRef.current) clearTimeout(timerRef.current)
      setCopied(true)
      timerRef.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      // Silently fail
    }
  }, [])

  return { copied, handleCopy }
}
