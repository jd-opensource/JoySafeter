'use client'

import { useCallback, useState } from 'react'

export function useCopyToClipboard(timeout = 2000) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), timeout)
        return true
      } catch {
        return false
      }
    },
    [timeout],
  )

  return { copied, handleCopy }
}
