'use client'

import { useState } from 'react'

import { useAvailableModels, useUpdateModelInstanceDefault } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'
import type { AvailableModel, ModelProvider } from '@/types/models'

import { ModelRow } from './model-row'
import { ParamDrawer } from './param-drawer'

interface ModelListTabProps {
  providerName: string
  provider: ModelProvider
}

export function ModelListTab({ providerName, provider }: ModelListTabProps) {
  const { data: availableModels = [] } = useAvailableModels('chat')
  const updateDefault = useUpdateModelInstanceDefault()
  const { toast } = useToast()

  const [editingModel, setEditingModel] = useState<AvailableModel | null>(null)

  const providerModels = availableModels.filter((m) => m.provider_name === providerName)

  const handleSetDefault = (modelName: string) => {
    updateDefault.mutate(
      { provider_name: providerName, model_name: modelName, is_default: true },
      {
        onSuccess: () => {
          toast({ title: `已设为默认模型: ${modelName}` })
        },
        onError: (err) => {
          toast({
            variant: 'destructive',
            title: '设置默认模型失败',
            description: err instanceof Error ? err.message : '请稍后重试',
          })
        },
      },
    )
  }

  if (providerModels.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[var(--text-muted)]">
        <p className="text-sm">该供应商暂无模型实例</p>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-2">
      {providerModels.map((model) => (
        <ModelRow
          key={model.name}
          model={model}
          onEditParams={() => setEditingModel(model)}
          onSetDefault={() => handleSetDefault(model.name)}
        />
      ))}

      {editingModel && (
        <ParamDrawer
          open={!!editingModel}
          onOpenChange={(open) => !open && setEditingModel(null)}
          instanceId={editingModel.instance_id}
          modelName={editingModel.name}
          modelParameters={editingModel.model_parameters ?? {}}
          configSchema={provider.config_schemas?.chat ?? null}
          providerDefaults={provider.default_parameters ?? {}}
        />
      )}
    </div>
  )
}
