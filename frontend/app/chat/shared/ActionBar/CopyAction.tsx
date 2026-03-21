'use client'

import { Check, Copy } from 'lucide-react'
import { useState } from 'react'

import { copyToClipboard } from '@/lib/utils/clipboard'

interface CopyActionProps {
  text: string
}

export function CopyAction({ text }: CopyActionProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await copyToClipboard(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Silently fail
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
      aria-label="Copy message"
    >
      {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
    </button>
  )
}
