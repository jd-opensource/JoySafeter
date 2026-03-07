'use client'

import { Settings, CheckCircle2, AlertCircle } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import type { ModelProvider, ModelCredential } from '@/hooks/queries/models'
import { truncateValidationError } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

interface CredentialPanelProps {
  provider: ModelProvider
  credential?: ModelCredential
  onSetup: () => void
}

export function CredentialPanel({ provider, credential, onSetup }: CredentialPanelProps) {
  const { t } = useTranslation()
  const hasCredential = !!credential
  const isValid = credential?.is_valid ?? false

  return (
    <div className="shrink-0 flex flex-col items-end gap-2 ml-2">
      {/* Status: 未配置(灰) / 有效(绿) / 验证未通过(橙) */}
      {!hasCredential ? (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium text-gray-500 bg-gray-50 border border-gray-200 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
          {t('settings.notConfigured')}
        </span>
      ) : isValid ? (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium text-green-600 bg-green-50 border border-green-200 rounded-full">
          <CheckCircle2 size={10} />
          {t('settings.valid')}
        </span>
      ) : (
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full"
          title={truncateValidationError(credential.validation_error)}
        >
          <AlertCircle size={10} />
          {t('settings.validationFailed')}
        </span>
      )}

      {/* Setup link */}
      <Button
        variant="ghost"
        size="sm"
        className="h-6 px-2 text-[10px] font-medium text-blue-600 hover:text-blue-700 hover:bg-blue-50"
        onClick={onSetup}
      >
        <Settings size={11} />
        {t('settings.setup')}
      </Button>
    </div>
  )
}
