'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, Loader2, Settings, Sparkles, Trash2, KeyRound } from 'lucide-react'
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
import { useAvailableModels, useDeleteModelProvider, useDeleteCredential } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/core/utils/cn'

import { ModelCredentialDialog } from './credential-dialog'
import { CredentialPanel } from './credential-panel'
import { ModelList } from './model-list'
import { ProviderIcon } from './provider-icon'

interface ModelProviderAddedCardProps {
  provider: ModelProvider
  credential?: ModelCredential
}

export function ModelProviderAddedCard({
  provider,
  credential,
}: ModelProviderAddedCardProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [collapsed, setCollapsed] = useState(true)
  const [showCredentialDialog, setShowCredentialDialog] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)

  const deleteProvider = useDeleteModelProvider()
  const deleteCredential = useDeleteCredential()
  const { data: models = [], isLoading: modelsLoading } = useAvailableModels('chat')

  const isCustom = provider.provider_type === 'custom'
  const hasCredential = !!credential
  const providerModels = models.filter(m => m.provider_name === provider.provider_name)
  const hasModels = providerModels.length > 0
  const supportedTypes = provider.supported_model_types || []

  const handleClearCredential = async () => {
    if (!credential?.id) return
    try {
      await deleteCredential.mutateAsync(credential.id)
      toast({
        variant: 'success',
        description: t('settings.credentialDeleted', { defaultValue: '凭据已清除' }),
      })
      setShowClearConfirm(false)
    } catch {
      toast({
        variant: 'destructive',
        description: t('settings.failedToDeleteCredential'),
      })
    }
  }

  return (
    <>
      <motion.div
        layout
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className={cn(
          'relative rounded-2xl border transition-all duration-300 overflow-hidden shadow-sm',
          isCustom
            ? 'bg-gradient-to-br from-violet-50/40 via-indigo-50/20 to-violet-50/40 border-violet-200'
            : 'bg-white border-gray-100'
        )}
      >
        {isCustom && (
          <div className="absolute top-0 right-0 p-3 pt-4">
            <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] font-bold tracking-wider uppercase bg-violet-100/80 text-violet-700 backdrop-blur-sm border border-violet-200 z-10">
              CUSTOM
            </span>
          </div>
        )}

        <div className="relative pl-5 py-5 pr-5">
          <div className="flex items-start gap-4">
            <ProviderIcon provider={provider} className="shadow-sm border border-gray-100/50 mt-1" />

            <div className="grow">
              <div className="flex items-baseline gap-2 mb-1">
                <h3 className="font-bold text-base text-gray-900">
                  {provider.display_name}
                </h3>
                {provider.credential_schema && (
                  <CredentialPanel
                    provider={provider}
                    credential={credential}
                    onSetup={() => setShowCredentialDialog(true)}
                  />
                )}
              </div>

              <div className="flex flex-wrap items-center gap-1.5 mt-2">
                {supportedTypes.map(modelType => (
                  <span
                    key={modelType}
                    className="px-1.5 py-0.5 text-[10px] font-bold text-gray-500 bg-gray-50 border border-gray-100 rounded"
                  >
                    {t(`settings.modelTypes.${modelType}` as any, { defaultValue: modelType.toUpperCase() })}
                  </span>
                ))}
              </div>
            </div>

            {/* Action Buttons Group: Bottom Right of the main header section */}
            <div className="absolute bottom-4 right-5 flex items-center gap-1.5">
              {isCustom && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 text-red-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                  onClick={(e) => {
                    e.stopPropagation()
                    setShowDeleteDialog(true)
                  }}
                  disabled={deleteProvider.isPending}
                  title={t('common.delete', { defaultValue: 'Delete Provider' })}
                >
                  <Trash2 size={16} />
                </Button>
              )}

              {hasCredential && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                  onClick={(e) => {
                    e.stopPropagation()
                    setShowClearConfirm(true)
                  }}
                  disabled={deleteCredential.isPending}
                  title={t('settings.clearCredential', { defaultValue: 'Clear Credentials' })}
                >
                  <KeyRound size={16} className="opacity-70" />
                </Button>
              )}

              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                onClick={(e) => {
                  e.stopPropagation()
                  setShowCredentialDialog(true)
                }}
                title={t('settings.setup', { defaultValue: 'Setup' })}
              >
                <Settings size={16} />
              </Button>
            </div>
          </div>
        </div>

        {/* Models Bar */}
        <div
          className={cn(
            "flex items-center justify-between px-5 py-3 border-t border-gray-100/60 bg-gray-50/30 cursor-pointer hover:bg-gray-50 transition-colors",
            !collapsed && "bg-gray-50"
          )}
          onClick={() => setCollapsed(!collapsed)}
        >
          <div className="flex items-center gap-2.5 text-xs font-semibold text-gray-500">
            <Sparkles size={14} className={cn("transition-colors", hasModels ? "text-blue-500" : "text-gray-400")} />
            <span>
              {hasModels
                ? t('settings.showModelsNum', { num: providerModels.length })
                : t('settings.showModels')}
            </span>
            {modelsLoading && <Loader2 className="animate-spin w-3 h-3 text-gray-400" />}
          </div>
          <motion.div
            animate={{ rotate: collapsed ? 0 : 180 }}
            transition={{ duration: 0.3 }}
          >
            <ChevronDown className="w-4 h-4 text-gray-400" />
          </motion.div>
        </div>

        <AnimatePresence>
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.3 }}
              className="overflow-hidden"
            >
              <ModelList
                provider={provider}
                models={providerModels}
                onCollapse={() => setCollapsed(true)}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* Delete Provider Confirmation */}
      {showDeleteDialog && (
        <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('settings.deleteProviderTitle', { defaultValue: 'Confirm Delete' })}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('settings.deleteProviderDescription', {
                  defaultValue: 'Are you sure you want to delete this provider? This will remove all related models and credentials.',
                  name: provider.display_name
                })}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('common.cancel', { defaultValue: 'Cancel' })}</AlertDialogCancel>
              <AlertDialogAction
                className="bg-red-600 hover:bg-red-700 text-white"
                onClick={async () => {
                  try {
                    await deleteProvider.mutateAsync(provider.provider_name)
                    toast({
                      variant: 'success',
                      description: t('settings.providerDeleted', { defaultValue: 'Provider deleted successfully' }),
                    })
                  } catch (error) {
                    toast({
                      variant: 'destructive',
                      description: error instanceof Error ? error.message : 'Failed to delete provider',
                    })
                  }
                }}
                disabled={deleteProvider.isPending}
              >
                {deleteProvider.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t('common.delete', { defaultValue: 'Delete' })}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}

      {/* Clear Credential Confirmation */}
      {showClearConfirm && (
        <AlertDialog open={showClearConfirm} onOpenChange={setShowClearConfirm}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('settings.clearCredential')}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('settings.deleteCredentialConfirm')}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('common.cancel', { defaultValue: 'Cancel' })}</AlertDialogCancel>
              <AlertDialogAction
                onClick={handleClearCredential}
                className="bg-red-600 hover:bg-red-700 text-white"
              >
                {deleteCredential.isPending ? t('common.processing', { defaultValue: 'Processing...' }) : t('common.confirm', { defaultValue: 'Confirm' })}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}

      {showCredentialDialog && (
        <ModelCredentialDialog
          provider={provider}
          credential={credential}
          open={showCredentialDialog}
          onOpenChange={setShowCredentialDialog}
        />
      )}
    </>
  )
}
