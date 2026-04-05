'use client'

import { useState } from 'react'

import { useAvailableModels } from '@/hooks/queries/models'
import type { AvailableModel, ModelProvider } from '@/types/models'

import { ModelRow } from './model-row'
import { ParamDrawer } from './param-drawer'

interface ModelListTabProps {
  providerName: string
  provider: ModelProvider
}

export function ModelListTab({ providerName, provider }: ModelListTabProps) {
  const { data: availableModels = [] } = useAvailableModels('chat')

  const [editingModel, setEditingModel] = useState<AvailableModel | null>(null)

  const providerModels = availableModels.filter((m) => m.provider_name === providerName)

  if (providerModels.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[var(--text-muted)]">
        <p className="text-sm">No model instances for this provider</p>
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
