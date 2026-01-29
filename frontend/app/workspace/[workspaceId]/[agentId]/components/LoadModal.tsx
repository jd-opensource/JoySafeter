'use client'

import { FolderOpen, Loader2, Box, Clock, Trash2 } from 'lucide-react'
import React, { useState, useEffect } from 'react'


import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ToastAction } from '@/components/ui/toast'
import { useToast } from '@/components/ui/use-toast'
import { useTranslation } from '@/lib/i18n'

import { agentService, AgentGraph } from '../services/agentService'

interface LoadModalProps {
  onClose: () => void
  onLoad: (graph: AgentGraph) => void
}

export const LoadModal: React.FC<LoadModalProps> = ({ onClose, onLoad }) => {
  const { t } = useTranslation()
  const [graphs, setGraphs] = useState<AgentGraph[]>([])
  const [loading, setLoading] = useState(true)
  const { toast: triggerToast } = useToast()

  useEffect(() => {
    const fetchGraphs = async () => {
      try {
        const data = await agentService.listGraphs()
        setGraphs(data)
      } catch (e) {
        console.error('Failed to load graphs', e)
      } finally {
        setLoading(false)
      }
    }
    fetchGraphs()
  }, [])

  const performDelete = async (id: string) => {
    setGraphs((prev) => prev.filter((g) => g.id !== id))
    try {
      await agentService.deleteGraph(id)
      triggerToast({
        title: t('workspace.graphDeleted'),
        description: t('workspace.graphDeletedDescription'),
      })
    } catch (e) {
      console.error('Delete failed', e)
      triggerToast({
        variant: 'destructive',
        title: t('workspace.deleteFailed'),
        description: t('workspace.deleteFailedDescription'),
      })
    }
  }

  const handleDeleteRequest = (e: React.MouseEvent, id: string, name: string) => {
    e.stopPropagation()

    triggerToast({
      variant: 'destructive',
      title: t('workspace.confirmDeletion'),
      description: t('workspace.confirmDeletionDescription', { name }),
      action: (
        <ToastAction
          altText="Delete"
          onClick={() => performDelete(id)}
          className="border-white/20 hover:bg-white/20 text-white"
        >
          {t('workspace.deleteNow')}
        </ToastAction>
      ),
    })
  }

  return (
    <Dialog open={true} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-gray-800">
            <FolderOpen size={18} className="text-blue-500" />
            {t('workspace.loadSavedGraph')}
          </DialogTitle>
        </DialogHeader>

        <div className="max-h-[60vh] overflow-y-auto custom-scrollbar min-h-[200px] p-1">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
                            <Loader2 size={24} className="animate-spin text-blue-500" />
                            <span className="text-sm">{t('workspace.fetchingProjects')}</span>
            </div>
          ) : graphs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
                            <Box size={32} className="opacity-20" />
                            <span className="text-sm">{t('workspace.noSavedGraphs')}</span>
            </div>
          ) : (
            <div className="space-y-2">
              {graphs.map((g) => (
                <div
                  key={g.id}
                  onClick={() => onLoad(g)}
                  className="flex items-center justify-between p-3 hover:bg-blue-50 hover:border-blue-100 border border-transparent rounded-xl cursor-pointer group transition-all"
                >
                  <div className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-gray-700">{g.name}</span>
                    <div className="flex items-center gap-2 text-[10px] text-gray-400">
                      <Clock size={10} />
                      <span>{new Date(g.createdAt).toLocaleString()}</span>
                      <span className="w-1 h-1 rounded-full bg-gray-300" />
                                            <span>
                                              {g.nodeCount ?? 0} {t('workspace.nodes')}
                                            </span>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={(e) => handleDeleteRequest(e, g.id, g.name)}
                    className="h-8 w-8 text-gray-400 hover:text-red-500 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all"
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
