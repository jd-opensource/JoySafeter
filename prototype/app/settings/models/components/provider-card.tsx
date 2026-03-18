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
          'group relative flex min-h-[160px] cursor-pointer flex-col overflow-hidden rounded-[1.4rem] border p-4 transition-all duration-300',
          isCustom
            ? 'border-[rgba(36,56,77,0.16)] bg-[linear-gradient(135deg,rgba(255,255,255,0.94),rgba(111,129,148,0.08))] hover:border-[var(--border-hover)] hover:shadow-[0_22px_46px_rgba(15,23,42,0.08)]'
            : 'border-[var(--border)] bg-[var(--surface-elevated)] shadow-sm hover:border-[var(--border-hover)] hover:shadow-[0_22px_46px_rgba(15,23,42,0.08)]'
        )}
        onClick={() => setShowCredentialDialog(true)}
      >
        {/* Background Decorative Element */}
        <div className={cn(
          "absolute -right-4 -bottom-4 h-24 w-24 rounded-full blur-2xl opacity-20 transition-opacity group-hover:opacity-35",
          isCustom ? "bg-[rgba(36,56,77,0.45)]" : "bg-[rgba(111,129,148,0.4)]"
        )} />

        {isCustom && (
          <div className="absolute top-0 right-0 p-3">
            <span className="inline-flex items-center rounded-full border border-[rgba(36,56,77,0.16)] bg-white/80 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.16em] text-[var(--brand-500)] backdrop-blur-sm">
              {isTemplate ? t('settings.template', { defaultValue: 'TEMPLATE' }) : t('settings.custom', { defaultValue: 'CUSTOM' })}
            </span>
          </div>
        )}

        {/* Header */}
        <div className="flex items-start gap-3 mb-3">
          <ProviderIcon provider={provider} className="mt-1 border border-[var(--divider)] shadow-sm" />
          <div className="grow">
            <h3 className="text-sm font-semibold leading-tight text-[var(--text-primary)]">
              {provider.display_name}
            </h3>
            <div className="mt-1 flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
              <Sparkles size={10} className={isCustom ? "text-[var(--brand-500)]" : "text-[var(--status-running)]"} />
              <span>{modelCount} {t('settings.modelsLabel')}</span>
            </div>
          </div>
        </div>

        {/* Description & Action Group */}
        <div className="relative flex-1 mb-2">
          <p className="h-[32px] pr-8 text-xs leading-relaxed text-[var(--text-secondary)] transition-colors group-hover:text-[var(--text-primary)] line-clamp-2">
            {provider.description || t('settings.providerDescriptionPlaceholder')}
          </p>

          <div className="absolute bottom-0 right-0 flex items-center gap-1">
            {isCustom && !isTemplate && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 rounded-full p-0 text-[var(--status-offline)] opacity-0 transition-opacity hover:bg-[rgba(156,68,56,0.08)] hover:text-[var(--status-offline)] group-hover:opacity-100"
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
                "h-8 w-8 rounded-full p-0 opacity-0 transition-opacity group-hover:opacity-100",
                isTemplate
                  ? "text-[var(--brand-500)] hover:bg-[rgba(36,56,77,0.08)]"
                  : "text-[var(--status-running)] hover:bg-[rgba(54,93,130,0.08)]"
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
              className="rounded-full border border-[var(--divider)] bg-white/80 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-[var(--text-secondary)]"
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
