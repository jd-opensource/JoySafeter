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
    if (confirm(`Are you sure you want to delete provider "${provider.display_name}"? This action cannot be undone.`)) {
      deleteProvider.mutate(provider.provider_name, {
        onSuccess: () => {
          toast({ title: `Deleted provider ${provider.display_name}` })
          onProviderDeleted?.()
        },
        onError: (err) => {
          toast({
            variant: 'destructive',
            title: 'Failed to delete provider',
            description: err instanceof Error ? err.message : 'Please try again later',
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
              Model List
            </TabsTrigger>
            <TabsTrigger value="playground" className="rounded-none border-b-2 border-transparent data-[state=active]:border-[var(--text-primary)] data-[state=active]:bg-transparent">
              Playground
            </TabsTrigger>
            <TabsTrigger value="stats" className="rounded-none border-b-2 border-transparent data-[state=active]:border-[var(--text-primary)] data-[state=active]:bg-transparent">
              Stats
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
