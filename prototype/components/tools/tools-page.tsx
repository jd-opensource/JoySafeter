'use client'

import { Loader2, PlugZap, Plus, Wrench } from 'lucide-react'
import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AddMcpDialog } from '@/components/settings/add-mcp-dialog'
import { BuiltinToolCard, McpServerCard } from '@/components/settings/mcp-server-card'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/use-toast'
import {
  type McpServer,
  useDeleteMcpServer,
  useMcpServers,
  useUpdateMcpServer,
} from '@/hooks/queries/mcp'
import { useBuiltinTools } from '@/hooks/queries/tools'

export const ToolsPage: React.FC = () => {
  const { t } = useTranslation()
  const [showAddMcp, setShowAddMcp] = useState(false)
  const [editingServer, setEditingServer] = useState<McpServer | null>(null)
  const { toast } = useToast()
  const { data: mcpServers = [], isLoading } = useMcpServers()
  const { data: builtinTools = [], isLoading: isLoadingBuiltin } = useBuiltinTools()
  const deleteMcpServer = useDeleteMcpServer()
  const updateMcpServer = useUpdateMcpServer()

  const handleDelete = async (serverId: string) => {
    if (!confirm(t('settings.deleteMcpConfirm'))) {
      return
    }

    try {
      await deleteMcpServer.mutateAsync({ serverId })
      toast({
        title: t('settings.success'),
        description: t('settings.mcpServerDeleted'),
      })
    } catch (error) {
      toast({
        title: t('settings.error'),
        description: error instanceof Error ? error.message : t('settings.failedToDelete'),
        variant: 'destructive',
      })
    }
  }

  const handleToggleEnabled = async (server: McpServer) => {
    try {
      await updateMcpServer.mutateAsync({
        serverId: server.id,
        updates: {
          enabled: !server.enabled,
        },
      })
      toast({
        title: t('settings.success'),
        description: server.enabled ? t('settings.mcpServerDisabled') : t('settings.mcpServerEnabled'),
      })
    } catch (error) {
      toast({
        title: t('settings.error'),
        description: error instanceof Error ? error.message : t('settings.failedToUpdate'),
        variant: 'destructive',
      })
    }
  }

  const totalTools = builtinTools.length + mcpServers.length

  return (
    <div className="executive-page executive-shell">
      <AddMcpDialog
        open={showAddMcp || !!editingServer}
        onOpenChange={(open) => {
          if (!open) {
            setShowAddMcp(false)
            setEditingServer(null)
          } else {
            setShowAddMcp(open)
          }
        }}
        editingServer={editingServer}
      />

      <div className="executive-page-content space-y-6">
        <header className="executive-header">
          <div className="space-y-4">
            <div className="executive-kicker">
              <PlugZap className="h-3.5 w-3.5" />
              Capability Registry
            </div>
            <div className="space-y-3">
              <h1 className="text-4xl font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
                {t('settings.toolsAndMcpTitle')}
              </h1>
              <p className="max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
                Govern built-in tools and external MCP connections from a single
                operating surface designed for enterprise review.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="quiet-badge">
              {totalTools} active entries
            </div>
            <Button
              onClick={() => setShowAddMcp(true)}
              className="btn-primary h-11 rounded-full px-5 text-sm"
            >
              <Plus className="mr-2 h-4 w-4" />
              {t('settings.addMcp')}
            </Button>
          </div>
        </header>

        <section className="grid gap-4 lg:grid-cols-[1.4fr_0.9fr]">
          <div className="surface-panel px-6 py-7 sm:px-8">
            <div className="space-y-6">
              <div className="space-y-3">
                <div className="section-label">Built-in Capabilities</div>
                <div className="executive-rule" />
                <p className="max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
                  Native tools remain visible as governed system capabilities rather
                  than developer clutter.
                </p>
              </div>

              {isLoading || isLoadingBuiltin ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
                </div>
              ) : builtinTools.length > 0 ? (
                <div className="space-y-3">
                  {builtinTools.map((tool) => (
                    <BuiltinToolCard
                      key={tool.id}
                      id={tool.id}
                      label={tool.label}
                      name={tool.name}
                      description={tool.description}
                      toolType={tool.toolType}
                      category={tool.category}
                      tags={tool.tags}
                    />
                  ))}
                </div>
              ) : (
                <div className="surface-panel-flat flex min-h-[220px] flex-col items-center justify-center gap-3 px-6 py-8 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full border border-[var(--divider)] bg-white/80 text-[var(--brand-500)]">
                    <Wrench className="h-5 w-5" />
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-base font-semibold text-[var(--text-primary)]">
                      {t('settings.noDescription', { defaultValue: 'No built-in tools yet' })}
                    </h3>
                    <p className="max-w-md text-sm leading-6 text-[var(--text-secondary)]">
                      System tools will appear here once they are provisioned for
                      this workspace.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="surface-panel px-6 py-7 sm:px-7">
            <div className="space-y-6">
              <div className="space-y-3">
                <div className="section-label">External Connections</div>
                <div className="executive-rule" />
                <p className="text-sm leading-6 text-[var(--text-secondary)]">
                  MCP servers are treated as governed external capabilities with
                  explicit activation and status visibility.
                </p>
              </div>

              {isLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
                </div>
              ) : mcpServers.length > 0 ? (
                <div className="space-y-3">
                  {mcpServers.map((server) => (
                    <McpServerCard
                      key={server.id}
                      server={server}
                      toolCount={server.toolCount}
                      onEdit={setEditingServer}
                      onToggleEnabled={handleToggleEnabled}
                      onDelete={handleDelete}
                      isUpdating={updateMcpServer.isPending}
                      isDeleting={deleteMcpServer.isPending}
                    />
                  ))}
                </div>
              ) : (
                <div
                  className="surface-panel-flat flex min-h-[240px] cursor-pointer flex-col items-center justify-center gap-3 px-6 py-8 text-center transition duration-200 hover:border-[var(--border-hover)] hover:bg-white"
                  onClick={() => setShowAddMcp(true)}
                >
                  <div className="flex h-12 w-12 items-center justify-center rounded-full border border-[var(--divider)] bg-white/80 text-[var(--brand-500)]">
                    <Plus className="h-5 w-5" />
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-base font-semibold text-[var(--text-primary)]">
                      {t('settings.connectNewServer')}
                    </h3>
                    <p className="max-w-sm text-sm leading-6 text-[var(--text-secondary)]">
                      {t('settings.connectNewServerDescription')}
                    </p>
                  </div>
                </div>
              )}

              {(builtinTools.length > 0 || mcpServers.length > 0) && (
                <button
                  type="button"
                  onClick={() => setShowAddMcp(true)}
                  className="surface-panel-flat flex w-full items-center justify-center gap-3 px-4 py-4 text-sm font-medium text-[var(--text-secondary)] transition duration-200 hover:border-[var(--border-hover)] hover:bg-white hover:text-[var(--text-primary)]"
                >
                  <Plus className="h-4 w-4" />
                  {t('settings.connectNewServer')}
                </button>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
