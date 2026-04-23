'use client'

import { ArrowLeft, Bot, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, usePathname } from 'next/navigation'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { Button } from '@/components/ui/button'
import { useAgent } from '@/hooks/queries/agents'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { cn } from '@/lib/utils'
import { WorkspacePermissionsProvider } from '@/providers/workspace-permissions-provider'

const NAV_ITEMS = [
  { label: '概览', labelEn: 'Overview', href: '' },
  { label: '构建', labelEn: 'Build', href: '/build' },
  { label: '运行记录', labelEn: 'Runs', href: '/runs' },
]

export default function AgentDetailLayout({ children }: { children: React.ReactNode }) {
  const params = useParams()
  const pathname = usePathname()
  const agentId = params.agentId as string

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent, isLoading } = useAgent(agentId, workspaceId)

  const basePath = `/agents/${agentId}`

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading...
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-sm text-[var(--text-muted)]">Agent not found</p>
        <Button variant="outline" size="sm" asChild>
          <Link href="/agents">Back to Agents</Link>
        </Button>
      </div>
    )
  }

  return (
    <WorkspacePermissionsProvider workspaceId={workspaceId}>
      <div className="flex h-full flex-col bg-[var(--bg)]">
        {/* Header */}
        <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-8 py-5">
          {/* Breadcrumb */}
          <div className="mb-3 flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
            <Link href="/agents" className="hover:text-[var(--text-secondary)]">
              我的助手
            </Link>
            <span>/</span>
            <span className="text-[var(--text-secondary)]">{agent.name}</span>
          </div>

          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" asChild className="h-8 w-8 p-0">
              <Link href="/agents">
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <Bot className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold text-[var(--text-primary)]">
                {agent.name}
              </h1>
            </div>
            <AgentStatusIndicator status={agent.status} className="ml-2" />
          </div>

          {/* Tab navigation */}
          <nav className="mt-4 flex gap-1">
            {NAV_ITEMS.map((item) => {
              const href = `${basePath}${item.href}`
              const isActive = item.href === ''
                ? pathname === basePath || pathname === `${basePath}/`
                : pathname?.startsWith(href)

              return (
                <Link
                  key={item.href}
                  href={href}
                  className={cn(
                    'rounded-md px-4 py-2 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-[var(--surface-3)] text-[var(--text-primary)]'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                  )}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </WorkspacePermissionsProvider>
  )
}
