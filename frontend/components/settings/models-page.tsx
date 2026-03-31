import { useState } from 'react'

import { AddCustomModelDialog } from '@/components/settings/models/add-custom-model-dialog'
import { DetailPanel } from '@/components/settings/models/detail-panel/detail-panel'
import { ProviderSidebar } from '@/components/settings/models/provider-sidebar/provider-sidebar'
import { useModelProviders } from '@/hooks/queries/models'

export function ModelsPage() {
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [showAddCustomModel, setShowAddCustomModel] = useState(false)
  const { data: providers = [] } = useModelProviders()

  const customProvider = providers.find((p) => p.provider_name === 'custom')

  return (
    <div className="flex h-full overflow-hidden">
      <ProviderSidebar
        selectedProvider={selectedProvider}
        onSelectProvider={setSelectedProvider}
        onAddCustomModel={() => setShowAddCustomModel(true)}
      />

      <DetailPanel selectedProvider={selectedProvider} />

      {customProvider && (
        <AddCustomModelDialog
          open={showAddCustomModel}
          onOpenChange={setShowAddCustomModel}
          provider={customProvider}
        />
      )}
    </div>
  )
}
