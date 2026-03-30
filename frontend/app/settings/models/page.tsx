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

  // custom 模板 provider 包含 credential_schema（协议类型、API Key、Base URL 等字段定义）
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
