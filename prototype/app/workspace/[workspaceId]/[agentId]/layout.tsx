import { ErrorBoundary } from '@/app/workspace/[workspaceId]/[agentId]/error-boundary'

/**
 * Agent Detail Layout
 *
 * Provides agent-level functionality:
 * - ErrorBoundary: catch and handle execution errors
 * - Set page base styles (overflow-hidden for canvas)
 */
export default function AgentLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className='h-full w-full overflow-hidden bg-muted/40'>
      <ErrorBoundary>{children}</ErrorBoundary>
    </main>
  )
}
