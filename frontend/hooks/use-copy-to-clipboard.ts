import { useCallback, useEffect, useRef, useState } from 'react'

export interface UseCopyToClipboardOptions {
  /** How long the `copied` flag stays true after a successful copy (ms). */
  resetDelayMs?: number
}

export interface UseCopyToClipboardResult {
  /** True for `resetDelayMs` after a successful copy. Drives the Copy→Check swap. */
  copied: boolean
  /** Copy plain text to the clipboard. */
  copy: (text: string) => Promise<void>
  /**
   * Copy rich HTML (with a plain-text fallback) to the clipboard. Falls back to
   * `writeText(fallbackText)` when the async Clipboard API or `ClipboardItem`
   * is unavailable. Used by the event detail "copy rendered content" action.
   */
  copyRich: (html: string, fallbackText: string) => Promise<void>
}

/**
 * Clipboard copy with a self-resetting "copied" flag.
 *
 * Consolidates the `useState(copied) + setTimeout + timer cleanup` block that
 * was re-implemented in api-keys, quickstart, event-detail, egress-editor, etc.
 * The reset timer is cancelled on unmount and re-armed on each copy.
 */
export function useCopyToClipboard(
  options: UseCopyToClipboardOptions = {},
): UseCopyToClipboardResult {
  const { resetDelayMs = 1500 } = options
  const [copied, setCopied] = useState(false)
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(
    () => () => {
      if (resetTimerRef.current) {
        clearTimeout(resetTimerRef.current)
      }
    },
    [],
  )

  const flagCopied = useCallback(() => {
    if (resetTimerRef.current) {
      clearTimeout(resetTimerRef.current)
    }
    setCopied(true)
    resetTimerRef.current = setTimeout(() => {
      setCopied(false)
      resetTimerRef.current = null
    }, resetDelayMs)
  }, [resetDelayMs])

  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard?.writeText(text)
        flagCopied()
      } catch {
        // Clipboard denied/unavailable — leave `copied` false.
      }
    },
    [flagCopied],
  )

  const copyRich = useCallback(
    async (html: string, fallbackText: string) => {
      try {
        const htmlBlob = new Blob([html], { type: 'text/html' })
        const textBlob = new Blob([fallbackText], { type: 'text/plain' })
        await navigator.clipboard.write([
          new ClipboardItem({ 'text/html': htmlBlob, 'text/plain': textBlob }),
        ])
        flagCopied()
      } catch {
        // Fallback: plain text only.
        try {
          await navigator.clipboard?.writeText(fallbackText)
          flagCopied()
        } catch {
          // give up silently
        }
      }
    },
    [flagCopied],
  )

  return { copied, copy, copyRich }
}
