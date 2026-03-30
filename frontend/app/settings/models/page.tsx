'use client'

import { useState } from 'react'

import { useModelProviders } from '@/hooks/queries/models'

import { AddCustomModelDialog } from './components/add-custom-model-dialog'
import { DetailPanel } from './components/detail-panel/detail-panel'
import { ProviderSidebar } from './components/provider-sidebar/provider-sidebar'

export default function ModelsPage() {
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [showAddCustomModel, setShowAddCustomModel] = useState(false)
  const { data: providers = [] } = useModelProviders()

  const customProvider = providers.find((p) => p.provider_name === 'custom') ?? {
    provider_name: 'custom',
    display_name: '自定义',
    supported_model_types: ['chat'],
    is_enabled: true,
  }

  return (
    <div className="flex h-full overflow-hidden">
      <ProviderSidebar
        selectedProvider={selectedProvider}
        onSelectProvider={setSelectedProvider}
        onAddCustomModel={() => setShowAddCustomModel(true)}
      />

      <DetailPanel selectedProvider={selectedProvider} />

      <AddCustomModelDialog
        open={showAddCustomModel}
        onOpenChange={setShowAddCustomModel}
        provider={customProvider}
      />
    </div>
  )
}
