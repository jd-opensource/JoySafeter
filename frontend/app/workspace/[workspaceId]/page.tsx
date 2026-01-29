'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { useGraphs, graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import { createLogger } from '@/lib/logs/console/logger'

import { agentService } from './[agentId]/services/agentService'



const logger = createLogger('WorkspaceDetailPage')

/**
 * Workspace Details Page - Redirect to first agent/graph
 *
 * Route structure:
 * - Current page: /workspace/[workspaceId]
 * - Redirects to: /workspace/[workspaceId]/[agentId]
 */
export default function WorkspaceDetailPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const queryClient = useQueryClient()
  const [hasAttemptedRedirect, setHasAttemptedRedirect] = useState(false)
  const [isCreating, setIsCreating] = useState(false)

  // Use React Query hook to get graph list (shared cache)
  const { data: graphs = [], isLoading } = useGraphs(workspaceId)

  useEffect(() => {
    if (hasAttemptedRedirect || isLoading) {
      return
    }

    if (graphs.length > 0 && graphs[0].id) {
      const firstGraph = graphs[0]
      logger.info('Redirecting to first graph', { workspaceId, graphId: firstGraph.id })
      setHasAttemptedRedirect(true)
      router.replace(`/workspace/${workspaceId}/${firstGraph.id}`)
    } else {
      // Workspace is empty, automatically create default graph
      const createDefaultGraph = async () => {
        if (isCreating) return
        setIsCreating(true)
        try {
          logger.info('Workspace is empty, creating default graph', { workspaceId })
          
          // Use agentService to create new graph
          const graphName = t('workspace.defaultGraphName')
          const graph = await agentService.createGraph({
            name: graphName,
            description: t('workspace.defaultGraphDescription'),
            color: '',
            workspaceId: workspaceId,
          })

          const graphId = graph.id
          logger.info('Graph created', { graphId })

          // Save graph state (empty graph)
          await agentService.saveGraphState({
            graphId,
            nodes: [],
            edges: [],
            viewport: { x: 0, y: 0, zoom: 1 },
          })

          logger.info('Default graph created and saved', { graphId })
          
          // Refresh sidebar graph list (invalidate React Query cache)
          await queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
          
          // Redirect to newly created graph
          setHasAttemptedRedirect(true)
          router.replace(`/workspace/${workspaceId}/${graphId}`)
        } catch (error) {
          logger.error('Failed to create default graph', { error })
          setHasAttemptedRedirect(true)
        } finally {
          setIsCreating(false)
        }
      }

      createDefaultGraph()
    }
  }, [graphs, workspaceId, router, hasAttemptedRedirect, isLoading, isCreating, t, queryClient])

  // Show loading state
  if (isLoading || isCreating) {
    return (
      <div className='flex h-full items-center justify-center'>
        <div className='text-center'>
          <Loader2 className='mx-auto h-8 w-8 animate-spin text-muted-foreground' />
          <p className='mt-4 text-sm text-muted-foreground'>
            {isCreating 
              ? t('workspace.creatingDefaultGraph')
              : t('workspace.loadingAgents')}
          </p>
        </div>
      </div>
    )
  }

  // Show loading while redirecting
  return (
    <div className='flex h-full items-center justify-center'>
      <div className='text-center'>
        <Loader2 className='mx-auto h-8 w-8 animate-spin text-muted-foreground' />
        <p className='mt-4 text-sm text-muted-foreground'>{t('workspace.redirecting')}</p>
      </div>
    </div>
  )
}
