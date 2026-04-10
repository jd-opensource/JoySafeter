'use client'

import type { ModelCredential, ModelProvider } from '@/types/models'

interface ProviderItemProps {
  provider: ModelProvider
  credential?: ModelCredential
  isSelected: boolean
  onClick: () => void
  modelCount: number
}

function StatusDot({ credential }: { credential?: ModelCredential }) {
  if (!credential) {
    return <span className="h-2 w-2 rounded-full bg-[var(--text-muted)] shrink-0" />
  }
  if (credential.is_valid) {
    return <span className="h-2 w-2 rounded-full bg-[var(--status-success)] shrink-0" />
  }
  return <span className="h-2 w-2 rounded-full bg-[var(--status-error)] shrink-0" />
}

export function ProviderItem({ provider, credential, isSelected, onClick, modelCount }: ProviderItemProps) {
  const initials = provider.display_name.slice(0, 2).toUpperCase()

  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left transition-colors ${
        isSelected
          ? 'bg-[var(--surface-3)] text-[var(--text-primary)]'
          : 'text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]'
      }`}
    >
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--surface-elevated)] text-xs font-bold text-[var(--text-secondary)] border border-[var(--border-muted)]">
        {initials}
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium leading-tight">{provider.display_name}</p>
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {modelCount > 0 && (
          <span className="rounded-full bg-[var(--surface-3)] px-1.5 py-0.5 text-xs text-[var(--text-muted)]">
            {modelCount}
          </span>
        )}
        <StatusDot credential={credential} />
      </div>
    </button>
  )
}
