'use client'

import { Settings, Cpu, Users } from 'lucide-react'
import Link from 'next/link'

import { Card } from '@/components/ui/card'
import { useWorkspaces } from '@/hooks/queries/workspaces'

export default function SettingsPage() {
  const { data: workspaces = [] } = useWorkspaces()
  const workspaceId = workspaces[0]?.id ?? ''

  const items = [
    {
      title: '模型配置',
      description: '管理模型供应商、凭据和配置',
      icon: Cpu,
      href: '/settings/models',
    },
    {
      title: '成员管理',
      description: '管理工作空间成员和权限',
      icon: Users,
      href: workspaceId ? `/settings/members/${workspaceId}` : '#',
    },
  ]

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-8 py-5">
        <div className="flex items-center gap-2">
          <Settings className="h-5 w-5 text-[var(--skill-brand-600)]" />
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">设置</h1>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {items.map((item) => (
            <Link key={item.href} href={item.href}>
              <Card className="flex items-start gap-4 border-[var(--border)] bg-[var(--surface-1)] p-5 transition-shadow hover:shadow-md">
                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--surface-3)]">
                  <item.icon className="h-5 w-5 text-[var(--text-secondary)]" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[var(--text-primary)]">{item.title}</h3>
                  <p className="mt-1 text-xs text-[var(--text-muted)]">{item.description}</p>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
