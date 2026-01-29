'use client'

import { Circle, Loader2 } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
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
    return <Circle className="w-4 h-4 text-gray-200" />
  }
  
  return (
    <div className={`
      w-4 h-4 rounded-full border-2 flex items-center justify-center
      ${selected 
        ? 'border-blue-500 bg-blue-500' 
        : 'border-gray-300 bg-white group-hover:border-blue-300'
      }
      transition-colors
    `}>
      {selected && (
        <div className="w-1.5 h-1.5 rounded-full bg-white" />
      )}
    </div>
  )
}

export function ModelListItem({ model, provider, isLast }: ModelListItemProps) {
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
      const errorMessage = error instanceof Error 
        ? error.message 
        : t('settings.failedToUpdateDefaultModel')
      toast({
        title: t('settings.error'),
        description: errorMessage,
        variant: 'destructive',
      })
    }
  }

  return (
    <div 
      className={`
        flex items-center justify-between px-4 py-2.5 
        hover:bg-blue-50/50 group transition-colors
        ${!isLast ? 'border-b border-gray-50' : ''}
        ${model.is_default ? 'bg-blue-50/30' : 'bg-white'}
        ${model.is_available && !model.is_default ? 'cursor-pointer' : ''}
      `}
      onClick={model.is_available && !model.is_default ? handleSetDefault : undefined}
    >
      {/* Left: Radio + Name */}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {/* Radio indicator */}
        <div className="shrink-0">
          <RadioIndicator 
            selected={model.is_default ?? false} 
            disabled={!model.is_available} 
          />
        </div>
        
        {/* Model info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-[13px] font-medium truncate ${model.is_available ? 'text-gray-800' : 'text-gray-400'}`}>
              {model.display_name || model.name}
            </span>
          </div>
          {model.description && (
            <p className="text-[11px] text-gray-400 mt-0.5 line-clamp-1">{model.description}</p>
          )}
        </div>
      </div>

      {/* Right: Status label */}
      <div className="shrink-0 ml-3 flex items-center gap-2">
        {updateDefault.isPending && (
          <Loader2 className="w-3 h-3 animate-spin text-blue-500" />
        )}
        {model.is_default && (
          <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-medium text-blue-600 bg-blue-100 rounded">
            {t('settings.systemDefault')}
          </span>
        )}
        {model.is_available && !model.is_default && !updateDefault.isPending && (
          <span className="text-[10px] text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">
            {t('settings.clickToSetDefault')}
          </span>
        )}
        {!model.is_available && (
          <span className="text-[10px] text-gray-300">
            {t('settings.unavailable')}
          </span>
        )}
      </div>
    </div>
  )
}

