'use client'

import { Settings, CheckCircle2, AlertCircle, Trash2 } from 'lucide-react'
import React, { useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import type { ModelProvider, ModelCredential } from '@/hooks/queries/models'
import { truncateValidationError, useDeleteCredential } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'

interface CredentialPanelProps {
  provider: ModelProvider
  credential?: ModelCredential
  onSetup: () => void
}

export function CredentialPanel({ provider, credential, onSetup }: CredentialPanelProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const deleteCredential = useDeleteCredential()
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false)

  const hasCredential = !!credential
  const isValid = credential?.is_valid ?? false

  const handleClearCredential = async () => {
    if (!credential?.id) return
    try {
      await deleteCredential.mutateAsync(credential.id)
      toast({
        variant: 'success',
        description: t('settings.credentialDeleted', { defaultValue: '凭据已清除' }),
      })
      setClearConfirmOpen(false)
    } catch {
      toast({
        variant: 'destructive',
        description: t('settings.failedToDeleteCredential'),
      })
    }
  }

  return (
    <>
      <div className="ml-2 flex shrink-0 flex-col items-end gap-2">
        {/* Status: 未配置(灰) / 有效(绿) / 验证未通过(橙) */}
        {!hasCredential ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-medium text-gray-500">
            <span className="h-1.5 w-1.5 rounded-full bg-gray-400" />
            {t('settings.notConfigured')}
          </span>
        ) : isValid ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-[10px] font-medium text-green-600">
            <CheckCircle2 size={10} />
            {t('settings.valid')}
          </span>
        ) : (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700"
            title={truncateValidationError(credential.validation_error)}
          >
            <AlertCircle size={10} />
            {t('settings.validationFailed')}
          </span>
        )}
      </div>

      <AlertDialog open={clearConfirmOpen} onOpenChange={setClearConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings.clearCredential')}</AlertDialogTitle>
            <AlertDialogDescription>{t('settings.deleteCredentialConfirm')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('settings.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleClearCredential}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteCredential.isPending
                ? t('settings.loading', { defaultValue: '处理中...' })
                : t('settings.confirm', { defaultValue: '确定' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
