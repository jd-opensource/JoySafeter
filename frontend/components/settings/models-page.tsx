import { useState } from 'react'

import { AddCustomModelDialog } from '@/components/settings/models/add-custom-model-dialog'
import { DetailPanel } from '@/components/settings/models/detail-panel/detail-panel'
import { ProviderSidebar } from '@/components/settings/models/provider-sidebar/provider-sidebar'
import { useModelProvider } from '@/hooks/queries/models'

export function ModelsPage() {
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [showAddCustomModel, setShowAddCustomModel] = useState(false)
  const { data: customTemplate } = useModelProvider('custom')

  const handleProviderDeleted = () => {
    setSelectedProvider(null)
  }

  return (
    <div className="flex h-full overflow-hidden">
      <ProviderSidebar
        selectedProvider={selectedProvider}
        onSelectProvider={setSelectedProvider}
        onAddCustomModel={() => setShowAddCustomModel(true)}
      />

      <DetailPanel
        selectedProvider={selectedProvider}
        onProviderDeleted={handleProviderDeleted}
      />

      <AddCustomModelDialog
        open={showAddCustomModel}
        onOpenChange={setShowAddCustomModel}
        credentialSchema={customTemplate?.credential_schema}
      />
    </div>
  )
}
