'use client'

import React, { useEffect } from 'react'
import { useRouter } from 'next/navigation'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { useWorkspaces } from '@/hooks/queries'
import { useAvailableModels } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

import { useChatState } from '../ChatProvider'

const MODEL_SETUP_DISMISSED_KEY = 'modelSetupPromptDismissed'

export function ModelNoticeDialog() {
  const { t } = useTranslation()
  const router = useRouter()
  const { state, dispatch } = useChatState()
  const { data: workspacesData } = useWorkspaces()
  const personalWorkspaceId = workspacesData?.find((w) => w.type === 'personal')?.id ?? null

  const {
    data: availableModels = [],
    isSuccess: modelsLoaded,
    isError: modelsError,
  } = useAvailableModels('chat', { enabled: true })

  const hasNoDefaultModel =
    modelsLoaded &&
    !modelsError &&
    (availableModels.length === 0 ||
      !availableModels.some((m) => m.is_default === true && m.is_available === true))

  // Show notice when no default model
  useEffect(() => {
    if (
      !personalWorkspaceId ||
      !hasNoDefaultModel ||
      typeof window === 'undefined' ||
      sessionStorage.getItem(MODEL_SETUP_DISMISSED_KEY) === '1'
    ) {
      return
    }
    dispatch({ type: 'SHOW_MODEL_NOTICE' })
  }, [personalWorkspaceId, hasNoDefaultModel, dispatch])

  // Auto-close if model configured elsewhere
  useEffect(() => {
    if (!hasNoDefaultModel && state.ui.showNoDefaultModelNotice) {
      dispatch({ type: 'DISMISS_MODEL_NOTICE' })
    }
  }, [hasNoDefaultModel, state.ui.showNoDefaultModelNotice, dispatch])

  return (
    <AlertDialog
      open={state.ui.showNoDefaultModelNotice}
      onOpenChange={(open) => {
        if (!open) dispatch({ type: 'DISMISS_MODEL_NOTICE' })
      }}
    >
      <AlertDialogContent hideCloseButton>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('chat.importantNotice')}</AlertDialogTitle>
          <AlertDialogDescription>{t('chat.noDefaultModelNotice')}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            onClick={() => {
              if (typeof window !== 'undefined') {
                sessionStorage.setItem(MODEL_SETUP_DISMISSED_KEY, '1')
              }
              dispatch({ type: 'DISMISS_MODEL_NOTICE' })
            }}
          >
            {t('chat.later')}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              if (personalWorkspaceId) {
                router.push('/settings/models')
              }
              dispatch({ type: 'DISMISS_MODEL_NOTICE' })
            }}
            className="bg-blue-600 hover:bg-blue-700"
          >
            {t('chat.goToModelSettings')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
