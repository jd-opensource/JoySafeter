'use client'

import { motion } from 'framer-motion'
import { Plus, Sparkles, Trash2, Loader2 } from 'lucide-react'
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
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

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
          'group relative flex min-h-[160px] cursor-pointer flex-col overflow-hidden rounded-2xl border p-4 transition-all duration-300',
          isCustom
            ? 'border-violet-200/60 bg-gradient-to-br from-violet-50/50 via-indigo-50/30 to-blue-50/20 hover:border-violet-400 hover:shadow-xl hover:shadow-violet-200/40'
            : 'border-gray-100 bg-white shadow-sm hover:border-blue-300 hover:shadow-xl hover:shadow-blue-100/50',
        )}
        onClick={() => setShowCredentialDialog(true)}
      >
        {/* Background Decorative Element */}
        <div
          className={cn(
            'absolute -bottom-4 -right-4 h-24 w-24 rounded-full opacity-20 blur-2xl transition-opacity group-hover:opacity-40',
            isCustom ? 'bg-violet-400' : 'bg-blue-400',
          )}
        />

        {isCustom && (
          <div className="absolute right-0 top-0 p-3">
            <span className="inline-flex items-center rounded-full border border-violet-200 bg-violet-100/80 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-violet-700 backdrop-blur-sm">
              {isTemplate
                ? t('settings.template', { defaultValue: 'TEMPLATE' })
                : t('settings.custom', { defaultValue: 'CUSTOM' })}
            </span>
          </div>
        )}

        {/* Header */}
        <div className="mb-3 flex items-start gap-3">
          <ProviderIcon provider={provider} className="mt-1 border border-gray-50 shadow-sm" />
          <div className="grow">
            <h3 className="text-sm font-bold leading-tight text-gray-900">
              {provider.display_name}
            </h3>
            <div className="mt-1 flex items-center gap-1 text-[10px] text-gray-400">
              <Sparkles size={10} className={isCustom ? 'text-violet-400' : 'text-blue-400'} />
              <span>
                {modelCount} {t('settings.modelsLabel')}
              </span>
            </div>
          </div>
        </div>

        {/* Description & Action Group */}
        <div className="relative mb-2 flex-1">
          <p className="line-clamp-2 h-[32px] pr-8 text-xs leading-relaxed text-gray-500 transition-colors group-hover:text-gray-600">
            {provider.description || t('settings.providerDescriptionPlaceholder')}
          </p>

          <div className="absolute bottom-0 right-0 flex items-center gap-1">
            {isCustom && !isTemplate && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 rounded-full p-0 text-red-500 opacity-0 transition-opacity hover:bg-red-50 hover:text-red-600 group-hover:opacity-100"
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
                'h-8 w-8 rounded-full p-0 opacity-0 transition-opacity group-hover:opacity-100',
                isTemplate
                  ? 'text-violet-600 hover:bg-violet-100'
                  : 'text-blue-600 hover:bg-blue-100',
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
        <div className="mt-auto flex flex-wrap gap-1">
          {supportedTypes.map((modelType) => (
            <span
              key={modelType}
              className="rounded-md border border-gray-100 bg-gray-50 px-1.5 py-0.5 text-[9px] font-bold text-gray-500"
            >
              {t(`settings.modelTypes.${modelType}` as any, {
                defaultValue: modelType.toUpperCase(),
              })}
            </span>
          ))}
        </div>
      </motion.div>

      {showDeleteDialog && (
        <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                {t('settings.deleteProviderTitle', { defaultValue: 'Confirm Delete' })}
              </AlertDialogTitle>
              <AlertDialogDescription>
                {t('settings.deleteProviderDescription', {
                  defaultValue:
                    'Are you sure you want to delete this provider? This will remove all related models and credentials.',
                  name: provider.display_name,
                })}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </AlertDialogCancel>
              <AlertDialogAction
                className="bg-red-600 text-white hover:bg-red-700"
                onClick={async () => {
                  try {
                    await deleteProvider.mutateAsync(provider.provider_name)
                    toast({
                      variant: 'success',
                      description: t('settings.providerDeleted', {
                        defaultValue: 'Provider deleted successfully',
                      }),
                    })
                  } catch (error) {
                    toast({
                      variant: 'destructive',
                      description:
                        error instanceof Error ? error.message : 'Failed to delete provider',
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
