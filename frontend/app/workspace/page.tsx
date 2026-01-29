'use client'

import { Loader2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useSession } from '@/lib/auth/auth-client'
import { createLogger } from '@/lib/logs/console/logger'

const logger = createLogger('WorkspacePage')

/**
 * Workspace Index Page
 *
 * Features:
 * 1. Get user's workspace list
 * 2. If no workspace exists, automatically create default workspace
 * 3. Redirect to first workspace
 *
 * Note: Authentication is handled by AuthGuard, no need to check again here
 */
export default function WorkspacePage() {
  const router = useRouter()
  const { data: session, isPending: isSessionPending } = useSession()
  
  // Use React Query hook to get workspace list (shared cache)
  const { data: workspaces = [], isLoading: isWorkspacesLoading } = useWorkspaces()

  useEffect(() => {
    // Wait for both session and workspaces to finish loading
    if (isSessionPending || isWorkspacesLoading) {
      return
    }

    // Ensure redirect happens on the correct path
    if (typeof window !== 'undefined' && window.location.pathname === '/workspace') {
      if (workspaces.length === 0) {
        logger.error('No workspaces found for user, personal space should have been created on login')
        router.replace('/')
        return
      }

      // Redirect to first workspace (usually personal space)
      const firstWorkspace = workspaces[0]
      logger.info(`Redirecting to first workspace: ${firstWorkspace.id}`)
      router.replace(`/workspace/${firstWorkspace.id}`)
    }
  }, [session, isSessionPending, isWorkspacesLoading, workspaces, router])

  if (isSessionPending || isWorkspacesLoading) {
    return (
      <div className='flex h-screen w-full items-center justify-center'>
        <div className='flex flex-col items-center justify-center text-center align-middle'>
          <Loader2 className='h-8 w-8 animate-spin text-muted-foreground' />
        </div>
      </div>
    )
  }

  return null
}
