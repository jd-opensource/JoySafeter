'use client'

import { Check, Copy } from 'lucide-react'

import { cn } from '@/lib/utils'

import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard'

export interface CopyButtonProps {
  /** Text copied to the clipboard on click. */
  value: string
  /** Extra classes merged onto the button. */
  className?: string
  /** Icon size in pixels (width & height). Default 14 (h-3.5 w-3.5). */
  iconSize?: number
  /** Accessible label / tooltip. */
  title?: string
}

/**
 * Icon button that copies `value` and briefly shows a check mark.
 *
 * Replaces the ad-hoc `copied` state + `setTimeout` + Copy/Check swap that was
 * duplicated across egress-editor, api-keys, quickstart, session views, etc.
 */
export function CopyButton({ value, className, iconSize = 14, title }: CopyButtonProps) {
  const { copied, copy } = useCopyToClipboard()
  const style = { width: iconSize, height: iconSize }

  return (
    <button
      type="button"
      title={title}
      aria-label={title ?? 'Copy'}
      className={cn(
        'shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
        className,
      )}
      onClick={() => {
        void copy(value)
      }}
    >
      {copied ? <Check style={style} /> : <Copy style={style} />}
    </button>
  )
}
