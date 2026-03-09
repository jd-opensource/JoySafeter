'use client'

import { motion } from 'framer-motion'
import { Plus, Sparkles, AlertCircle, Trash2, Loader2 } from 'lucide-react'
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
import { useDeleteModelProvider } from '@/hooks/queries/models'
import type { ModelProvider } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/core/utils/cn'

import { ModelCredentialDialog } from './credential-dialog'
import { ProviderIcon } from './provider-icon'

interface ModelProviderCardProps {
  provider: ModelProvider
}

export function ModelProviderCard({ provider }: ModelProviderCardProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [showCredentialDialog, setShowCredentialDialog] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const deleteProvider = useDeleteModelProvider()

  const isCustom = provider.provider_type === 'custom'
  const isTemplate = provider.is_template

  const supportedTypes = provider.supported_model_types || []
  const modelCount = (provider as any).model_count || supportedTypes.length

  return (
    <>
      <motion.div
        whileHover={{ y: -4, transition: { duration: 0.2 } }}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className={cn(
          'group relative flex flex-col p-4 min-h-[160px] rounded-2xl border transition-all duration-300 cursor-pointer overflow-hidden',
          isCustom
            ? 'bg-gradient-to-br from-violet-50/50 via-indigo-50/30 to-blue-50/20 border-violet-200/60 hover:border-violet-400 hover:shadow-xl hover:shadow-violet-200/40'
            : 'bg-white border-gray-100 hover:border-blue-300 hover:shadow-xl hover:shadow-blue-100/50 shadow-sm'
        )}
        onClick={() => setShowCredentialDialog(true)}
      >
        {/* Background Decorative Element */}
        <div className={cn(
          "absolute -right-4 -bottom-4 w-24 h-24 rounded-full blur-2xl opacity-20 transition-opacity group-hover:opacity-40",
          isCustom ? "bg-violet-400" : "bg-blue-400"
        )} />

        {isCustom && (
          <div className="absolute top-0 right-0 p-3">
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wider uppercase bg-violet-100/80 text-violet-700 backdrop-blur-sm border border-violet-200">
              {isTemplate ? t('settings.template', { defaultValue: 'TEMPLATE' }) : t('settings.custom', { defaultValue: 'CUSTOM' })}
            </span>
          </div>
        )}

        {/* Header */}
        <div className="flex items-start gap-3 mb-3">
          <ProviderIcon provider={provider} className="shadow-sm border border-gray-50 mt-1" />
          <div className="grow">
            <h3 className="font-bold text-sm text-gray-900 leading-tight">
              {provider.display_name}
            </h3>
            <div className="flex items-center gap-1 text-[10px] text-gray-400 mt-1">
              <Sparkles size={10} className={isCustom ? "text-violet-400" : "text-blue-400"} />
              <span>{modelCount} {t('settings.modelsLabel')}</span>
            </div>
          </div>
        </div>

        {/* Description & Action Group */}
        <div className="relative flex-1 mb-2">
          <p className="text-xs text-gray-500 line-clamp-2 leading-relaxed h-[32px] pr-8 group-hover:text-gray-600 transition-colors">
            {provider.description || t('settings.providerDescriptionPlaceholder')}
          </p>

          <div className="absolute bottom-0 right-0 flex items-center gap-1">
            {isCustom && !isTemplate && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0 rounded-full text-red-500 hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={(e) => {
                  e.stopPropagation()
                  setShowDeleteDialog(true)
                }}
                disabled={deleteProvider.isPending}
              >
                <Trash2 size={16} />
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className={cn(
                "h-8 w-8 p-0 rounded-full opacity-0 group-hover:opacity-100 transition-opacity",
                isTemplate ? "text-violet-600 hover:bg-violet-100" : "text-blue-600 hover:bg-blue-100"
              )}
              onClick={(e) => {
                e.stopPropagation()
                setShowCredentialDialog(true)
              }}
            >
              <Plus size={16} />
            </Button>
          </div>
        </div>

        {/* Footer tags */}
        <div className="flex flex-wrap gap-1 mt-auto">
          {supportedTypes.map(modelType => (
            <span
              key={modelType}
              className="px-1.5 py-0.5 text-[9px] font-bold text-gray-500 bg-gray-50 border border-gray-100 rounded-md"
            >
              {t(`settings.modelTypes.${modelType}` as any, { defaultValue: modelType.toUpperCase() })}
            </span>
          ))}
        </div>
      </motion.div>

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

      {showCredentialDialog && (
        <ModelCredentialDialog
          provider={provider}
          open={showCredentialDialog}
          onOpenChange={setShowCredentialDialog}
        />
      )}
    </>
  )
}
