'use client'

import { ChevronDown, ChevronUp, Settings2 } from 'lucide-react'
import { useState } from 'react'

import { OpenClawManagement } from './components/OpenClawManagement'
import { OpenClawWebUI } from './components/OpenClawWebUI'
import { cn } from '@/lib/core/utils/cn'

export default function OpenClawPage() {
  const [managementOpen, setManagementOpen] = useState(true)

  return (
    <div className="flex h-full flex-col overflow-hidden p-6">
      <div className="mb-4 shrink-0">
        <h1 className="text-2xl font-bold tracking-tight text-[var(--text-primary)]">
          OpenClaw
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          管理实例与设备配对后，在下方使用 OpenClaw 原生界面与 Agent 交互。
        </p>
      </div>

      <div className="mb-4 shrink-0 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
        <button
          type="button"
          onClick={() => setManagementOpen((o) => !o)}
          className={cn(
            'flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors',
            'hover:bg-[var(--muted)]/50',
          )}
          aria-expanded={managementOpen}
        >
          <span className="flex items-center gap-2.5 text-sm font-medium text-[var(--text-primary)]">
            <Settings2 className="h-4 w-4 text-[var(--text-tertiary)]" />
            实例与设备管理
          </span>
          <span className="flex h-8 w-8 items-center justify-center rounded-md text-[var(--text-tertiary)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--text-primary)]">
            {managementOpen ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </span>
        </button>
        {managementOpen && (
          <div className="border-t border-[var(--border)] p-4">
            <OpenClawManagement />
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1">
        <OpenClawWebUI />
      </div>
    </div>
  )
}
