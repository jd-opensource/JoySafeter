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
      className="rounded-md p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
      aria-label="Copy message"
    >
      {copied ? <Check size={14} className="text-[var(--status-success)]" /> : <Copy size={14} />}
    </button>
  )
}
