'use client'

import { useState } from 'react'

import { useAvailableModels, useModelInstances, useUpdateModelInstanceDefault } from '@/hooks/queries/models'
import type { ModelInstance, ModelProvider } from '@/types/models'

import { ModelRow } from './model-row'
import { ParamDrawer } from './param-drawer'

interface ModelListTabProps {
  providerName: string
  provider: ModelProvider
}

export function ModelListTab({ providerName, provider }: ModelListTabProps) {
  const { data: availableModels = [] } = useAvailableModels('chat')
  const { data: instances = [] } = useModelInstances()
  const updateDefault = useUpdateModelInstanceDefault()

  const [editingInstance, setEditingInstance] = useState<ModelInstance | null>(null)

  const providerModels = availableModels.filter((m) => m.provider_name === providerName)
  const instanceMap = new Map(instances.map((i) => [i.model_name, i]))

  const handleSetDefault = (modelName: string) => {
    updateDefault.mutate({ provider_name: providerName, model_name: modelName, is_default: true })
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
      {providerModels.map((model) => {
        const instance = instanceMap.get(model.name)
        return (
          <ModelRow
            key={model.name}
            model={model}
            instance={instance}
            onEditParams={() => instance && setEditingInstance(instance)}
            onSetDefault={() => handleSetDefault(model.name)}
          />
        )
      })}

      {editingInstance && (
        <ParamDrawer
          open={!!editingInstance}
          onOpenChange={(open) => !open && setEditingInstance(null)}
          instance={editingInstance}
          configSchema={provider.config_schemas ?? null}
          providerDefaults={provider.default_parameters ?? {}}
        />
      )}
    </div>
  )
}
