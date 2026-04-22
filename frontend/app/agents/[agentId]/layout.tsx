'use client'

import { ArrowLeft, Bot, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, usePathname } from 'next/navigation'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { Button } from '@/components/ui/button'
import { useAgent } from '@/hooks/queries/agents'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { label: 'Overview', href: '' },
  { label: 'Edit', href: '/edit' },
  { label: 'Versions', href: '/versions' },
  { label: 'Releases', href: '/releases' },
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
        Loading agent...
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
    <div className="flex h-full flex-col bg-[var(--bg)]">
      {/* Header */}
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/agents">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <Bot className="h-5 w-5 text-[var(--skill-brand-600)]" />
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-[var(--text-primary)]">
              {agent.name}
            </h1>
            <p className="text-xs text-[var(--text-muted)]">{agent.slug}</p>
          </div>
          <AgentStatusIndicator status={agent.status} className="ml-2" />
        </div>

        {/* Sub-navigation */}
        <nav className="mt-3 flex gap-1">
          {NAV_ITEMS.map((item) => {
            const href = `${basePath}${item.href}`
            const isActive = item.href === ''
              ? pathname === basePath
              : pathname.startsWith(href)

            return (
              <Link
                key={item.href}
                href={href}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
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
  )
}
