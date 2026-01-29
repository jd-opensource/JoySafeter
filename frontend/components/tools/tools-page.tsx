'use client'

import { Plus, Loader2 } from 'lucide-react';
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { AddMcpDialog } from '@/components/settings/add-mcp-dialog';
import { McpServerCard, BuiltinToolCard } from '@/components/settings/mcp-server-card';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/use-toast';
import { useMcpServers, useDeleteMcpServer, useUpdateMcpServer, type McpServer } from '@/hooks/queries/mcp';
import { useBuiltinTools } from '@/hooks/queries/tools';

export const ToolsPage: React.FC = () => {
    const { t } = useTranslation();
    const [showAddMcp, setShowAddMcp] = useState(false);
    const [editingServer, setEditingServer] = useState<McpServer | null>(null);
    const { toast } = useToast();
    const { data: mcpServers = [], isLoading } = useMcpServers();
    const { data: builtinTools = [], isLoading: isLoadingBuiltin } = useBuiltinTools();
    const deleteMcpServer = useDeleteMcpServer();
    const updateMcpServer = useUpdateMcpServer();

    const handleDelete = async (serverId: string) => {
        if (!confirm(t('settings.deleteMcpConfirm'))) {
            return;
        }

        try {
            await deleteMcpServer.mutateAsync({ serverId });
            toast({
                title: t('settings.success'),
                description: t('settings.mcpServerDeleted'),
            });
        } catch (error) {
            toast({
                title: t('settings.error'),
                description: error instanceof Error ? error.message : t('settings.failedToDelete'),
                variant: 'destructive',
            });
        }
    };

    /**
     * 切换 MCP 服务器启用状态
     */
    const handleToggleEnabled = async (server: McpServer) => {
        try {
            await updateMcpServer.mutateAsync({
                serverId: server.id,
                updates: {
                    enabled: !server.enabled,
                },
            });
            toast({
                title: t('settings.success'),
                description: server.enabled ? t('settings.mcpServerDisabled') : t('settings.mcpServerEnabled'),
            });
        } catch (error) {
            toast({
                title: t('settings.error'),
                description: error instanceof Error ? error.message : t('settings.failedToUpdate'),
                variant: 'destructive',
            });
        }
    };

    return (
        <div className="flex flex-col h-full bg-white">
            <AddMcpDialog 
                open={showAddMcp || !!editingServer} 
                onOpenChange={(open) => {
                    if (!open) {
                        setShowAddMcp(false);
                        setEditingServer(null);
                    } else {
                        setShowAddMcp(open);
                    }
                }}
                editingServer={editingServer}
            />
            
            <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-white">
                <div>
                    <h2 className="text-lg font-bold text-gray-900">{t('settings.toolsAndMcpTitle')}</h2>
                    <p className="text-xs text-gray-500 mt-1">{t('settings.toolsAndMcpDescription')}</p>
                </div>
                <Button 
                    onClick={() => setShowAddMcp(true)}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white shadow-emerald-100 shadow-lg gap-2 text-xs h-9"
                >
                    <Plus size={14} /> {t('settings.addMcp')}
                </Button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 bg-gray-50/50 space-y-6">
                {isLoading || isLoadingBuiltin ? (
                    <div className="flex items-center justify-center py-12">
                        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
                    </div>
                ) : (
                    <>
                        {/* Built-in Tools List (from Tool API) */}
                        {builtinTools.length > 0 && (
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
                        )}

                        {/* MCP Servers List */}
                        {mcpServers.length > 0 && (
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
                        )}

                        {builtinTools.length === 0 && mcpServers.length === 0 && (
                            <div className="p-4 rounded-xl border border-dashed border-gray-300 flex flex-col items-center justify-center text-center gap-2 bg-gray-50 hover:bg-white hover:border-gray-400 transition-colors cursor-pointer" onClick={() => setShowAddMcp(true)}>
                                <div className="w-10 h-10 rounded-full bg-white border border-gray-200 flex items-center justify-center shadow-sm text-gray-400">
                                    <Plus size={20} />
                                </div>
                                <div>
                                    <h4 className="text-sm font-medium text-gray-900">{t('settings.connectNewServer')}</h4>
                                    <p className="text-xs text-gray-500 mt-1">{t('settings.connectNewServerDescription')}</p>
                                </div>
                            </div>
                        )}

                        {(builtinTools.length > 0 || mcpServers.length > 0) && (
                            <div className="p-4 rounded-xl border border-dashed border-gray-300 flex flex-col items-center justify-center text-center gap-2 bg-gray-50 hover:bg-white hover:border-gray-400 transition-colors cursor-pointer" onClick={() => setShowAddMcp(true)}>
                                <div className="w-10 h-10 rounded-full bg-white border border-gray-200 flex items-center justify-center shadow-sm text-gray-400">
                                    <Plus size={20} />
                                </div>
                                <div>
                                    <h4 className="text-sm font-medium text-gray-900">{t('settings.connectNewServer')}</h4>
                                    <p className="text-xs text-gray-500 mt-1">{t('settings.connectNewServerDescription')}</p>
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
};

