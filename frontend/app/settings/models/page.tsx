'use client'

import { useState } from 'react'

import { useModelProvider } from '@/hooks/queries/models'

import { AddCustomModelDialog } from '@/components/settings/models/add-custom-model-dialog'
import { DetailPanel } from '@/components/settings/models/detail-panel/detail-panel'
import { ProviderSidebar } from '@/components/settings/models/provider-sidebar/provider-sidebar'

export default function ModelsPage() {
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [showAddCustomModel, setShowAddCustomModel] = useState(false)
  const { data: customTemplate } = useModelProvider('custom')

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
        credentialSchema={customTemplate?.credential_schema}
      />
    </div>
  )
}
