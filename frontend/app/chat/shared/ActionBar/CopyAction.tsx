'use client'

import { Check, Copy } from 'lucide-react'

import { useCopyToClipboard } from '../hooks/useCopyToClipboard'

interface CopyActionProps {
  text: string
}

export function CopyAction({ text }: CopyActionProps) {
  const { copied, handleCopy } = useCopyToClipboard()

  return (
    <button
      onClick={() => handleCopy(text)}
      className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
      aria-label="Copy message"
    >
      {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
    </button>
  )
}
