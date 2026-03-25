'use client'

import { Circle, Loader2 } from 'lucide-react'
import React from 'react'

import { useUpdateModelInstanceDefault } from '@/hooks/queries/models'
import type { ModelProvider, AvailableModel } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'

interface ModelListItemProps {
  model: AvailableModel
  provider: ModelProvider
  isLast?: boolean
}

// Radio style component
function RadioIndicator({ selected, disabled }: { selected: boolean; disabled?: boolean }) {
  if (disabled) {
    return <Circle className="h-4 w-4 text-[var(--surface-5)]" />
  }

  return (
    <div
      className={`flex h-4 w-4 items-center justify-center rounded-full border-2 ${
        selected
          ? 'border-[var(--brand-500)] bg-[var(--brand-500)]'
          : 'border-[var(--border-strong)] bg-[var(--surface-elevated)] group-hover:border-primary/30'
      } transition-colors`}
    >
      {selected && <div className="h-1.5 w-1.5 rounded-full bg-white" />}
    </div>
  )
}

export function ModelListItem({ model, provider: _provider, isLast }: ModelListItemProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const updateDefault = useUpdateModelInstanceDefault()

  const handleSetDefault = async () => {
    if (!model.is_available) {
      toast({
        title: t('settings.error'),
        description: t('settings.cannotSetUnavailableModelAsDefault'),
        variant: 'destructive',
      })
      return
    }

    try {
      await updateDefault.mutateAsync({
        provider_name: model.provider_name,
        model_name: model.name,
        is_default: true,
      })
      toast({
        variant: 'success',
        description: t('settings.defaultModelUpdated'),
      })
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : t('settings.failedToUpdateDefaultModel')
      toast({
        title: t('settings.error'),
        description: errorMessage,
        variant: 'destructive',
      })
    }
  }

  return (
    <div
      className={`group flex items-center justify-between px-4 py-2.5 transition-colors hover:bg-[var(--brand-50)] ${!isLast ? 'border-b border-[var(--surface-1)]' : ''} ${model.is_default ? 'bg-[var(--brand-50)]' : 'bg-[var(--surface-elevated)]'} ${model.is_available && !model.is_default ? 'cursor-pointer' : ''} `}
      onClick={model.is_available && !model.is_default ? handleSetDefault : undefined}
    >
      {/* Left: Radio + Name */}
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {/* Radio indicator */}
        <div className="shrink-0">
          <RadioIndicator selected={model.is_default ?? false} disabled={!model.is_available} />
        </div>

        {/* Model info */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`truncate text-[13px] font-medium ${model.is_available ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}
            >
              {model.display_name || model.name}
            </span>
          </div>
          {model.description && (
            <p className="mt-0.5 line-clamp-1 text-[11px] text-[var(--text-muted)]">{model.description}</p>
          )}
        </div>
      </div>

      {/* Right: Status label */}
      <div className="ml-3 flex shrink-0 items-center gap-2">
        {updateDefault.isPending && <Loader2 className="h-3 w-3 animate-spin text-[var(--brand-500)]" />}
        {model.is_default && (
          <span className="inline-flex items-center rounded bg-[var(--brand-100)] px-2 py-0.5 text-[10px] font-medium text-[var(--brand-600)]">
            {t('settings.systemDefault')}
          </span>
        )}
        {model.is_available && !model.is_default && !updateDefault.isPending && (
          <span className="text-[10px] text-[var(--text-muted)] opacity-0 transition-opacity group-hover:opacity-100">
            {t('settings.clickToSetDefault')}
          </span>
        )}
        {!model.is_available && (
          <span className="text-[10px] text-[var(--text-subtle)]">{t('settings.unavailable')}</span>
        )}
      </div>
    </div>
  )
}
