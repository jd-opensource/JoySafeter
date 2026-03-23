'use client'

import { Check, Copy, X } from 'lucide-react'
import { useState, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { useTranslation } from '@/lib/i18n'

interface TokenCreatedDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  token: string | null
}

export function TokenCreatedDialog({ open, onOpenChange, token }: TokenCreatedDialogProps) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    if (!token) return
    await navigator.clipboard.writeText(token)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [token])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-md gap-0 overflow-hidden border-0 bg-[#F9F9FA] p-0 shadow-2xl sm:rounded-2xl"
        hideCloseButton
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 bg-white px-6 py-4">
          <DialogTitle className="text-base font-bold text-gray-900">
            {t('settings.tokens.tokenCreatedTitle')}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t('settings.tokens.tokenCreatedMessage')}
          </DialogDescription>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-full p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="space-y-4 bg-[#F9F9FA] p-6">
          <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-4 py-3 border border-amber-200">
            {t('settings.tokens.tokenCreatedMessage')}
          </p>

          {token && (
            <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
              <div className="flex items-center justify-between gap-2 px-4 py-3">
                <span className="font-mono text-xs text-gray-700 break-all select-all flex-1">
                  {token}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={handleCopy}
                  className="h-8 w-8 shrink-0 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                >
                  {copied ? <Check size={15} className="text-emerald-600" /> : <Copy size={15} />}
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-gray-100 bg-white p-6">
          <Button
            type="button"
            onClick={handleCopy}
            className="gap-2"
            disabled={!token}
          >
            {copied ? (
              <>
                <Check size={16} />
                {t('settings.tokens.copied')}
              </>
            ) : (
              <>
                <Copy size={16} />
                {t('settings.tokens.copyToken')}
              </>
            )}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {t('settings.cancel')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
