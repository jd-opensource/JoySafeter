'use client'

import { useState } from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDeleteModelProvider, useModelCredentials, useModelProviders } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'

import { CredentialDialog } from '../credential-dialog'
import { ModelListTab } from './model-list-tab/model-list-tab'
import { OverviewDashboard } from './overview-dashboard'
import { PlaygroundTab } from './playground-tab/playground-tab'
import { ProviderHeader } from './provider-header'
import { StatsTab } from './stats-tab/stats-tab'

interface DetailPanelProps {
  selectedProvider: string | null
  onProviderDeleted?: () => void
}

export function DetailPanel({ selectedProvider, onProviderDeleted }: DetailPanelProps) {
  const [showCredentialDialog, setShowCredentialDialog] = useState(false)
  const { data: providers = [] } = useModelProviders()
  const { data: credentials = [] } = useModelCredentials()
  const deleteProvider = useDeleteModelProvider()
  const { toast } = useToast()

  const provider = providers.find((p) => p.provider_name === selectedProvider)
  const credential = credentials.find((c) => c.provider_name === selectedProvider)

  if (!selectedProvider || !provider) {
    return (
      <div className="flex-1 overflow-y-auto bg-[var(--surface-elevated)]">
        <OverviewDashboard />
      </div>
    )
  }

  const handleDeleteProvider = () => {
    if (confirm(`确定要删除供应商 "${provider.display_name}" 吗？此操作不可撤销。`)) {
      deleteProvider.mutate(provider.provider_name, {
        onSuccess: () => {
          toast({ title: `已删除供应商 ${provider.display_name}` })
          onProviderDeleted?.()
        },
        onError: (err) => {
          toast({
            variant: 'destructive',
            title: '删除供应商失败',
            description: err instanceof Error ? err.message : '请稍后重试',
          })
        },
      })
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-[var(--surface-elevated)]">
      <ProviderHeader
        provider={provider}
        credential={credential}
        onEditCredential={() => setShowCredentialDialog(true)}
        onDeleteProvider={provider.provider_type === 'custom' ? handleDeleteProvider : undefined}
      />

      <Tabs defaultValue="models" className="flex flex-1 flex-col overflow-hidden">
        <div className="border-b border-[var(--border-muted)] px-6">
          <TabsList className="h-10 bg-transparent p-0">
            <TabsTrigger value="models" className="rounded-none border-b-2 border-transparent data-[state=active]:border-[var(--text-primary)] data-[state=active]:bg-transparent">
              模型列表
            </TabsTrigger>
            <TabsTrigger value="playground" className="rounded-none border-b-2 border-transparent data-[state=active]:border-[var(--text-primary)] data-[state=active]:bg-transparent">
              Playground
            </TabsTrigger>
            <TabsTrigger value="stats" className="rounded-none border-b-2 border-transparent data-[state=active]:border-[var(--text-primary)] data-[state=active]:bg-transparent">
              统计
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="models" className="flex-1 overflow-y-auto m-0">
          <ModelListTab providerName={selectedProvider} provider={provider} />
        </TabsContent>

        <TabsContent value="playground" className="flex-1 overflow-y-auto m-0 p-6">
          <PlaygroundTab providerName={selectedProvider} provider={provider} />
        </TabsContent>

        <TabsContent value="stats" className="flex-1 overflow-y-auto m-0 p-6">
          <StatsTab providerName={selectedProvider} />
        </TabsContent>
      </Tabs>

      <CredentialDialog
        open={showCredentialDialog}
        onOpenChange={setShowCredentialDialog}
        provider={provider}
        existingCredential={credential}
      />
    </div>
  )
}
