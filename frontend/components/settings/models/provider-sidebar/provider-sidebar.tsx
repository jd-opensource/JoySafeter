'use client'

import { Plus } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useModelCredentials, useModelProviders, useModelProvidersByConfig } from '@/hooks/queries/models'

import { ProviderItem } from './provider-item'
import { ProviderSearch } from './provider-search'

interface ProviderSidebarProps {
  selectedProvider: string | null
  onSelectProvider: (name: string | null) => void
  onAddCustomModel?: () => void
}

export function ProviderSidebar({ selectedProvider, onSelectProvider, onAddCustomModel }: ProviderSidebarProps) {
  const [search, setSearch] = useState('')
  const { data: providers = [] } = useModelProviders()
  const { data: credentials = [] } = useModelCredentials()
  const { credentialsByProvider } = useModelProvidersByConfig(providers, credentials)

  const filtered = useMemo(() => {
    if (!search.trim()) return providers
    const q = search.toLowerCase()
    return providers.filter(
      (p) =>
        p.display_name.toLowerCase().includes(q) ||
        p.provider_name.toLowerCase().includes(q),
    )
  }, [providers, search])

  const systemProviders = filtered.filter((p) => p.provider_type !== 'custom' && !p.is_template)
  const customProviders = filtered.filter((p) => p.provider_type === 'custom')

  return (
    <div className="flex w-[260px] shrink-0 flex-col border-r border-[var(--border-muted)] bg-[var(--surface-elevated)]">
      <div className="flex items-center justify-between border-b border-[var(--border-muted)] p-3">
        <span className="text-xs font-semibold text-[var(--text-tertiary)]">供应商</span>
        <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={onAddCustomModel}>
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="p-2">
        <ProviderSearch value={search} onChange={setSearch} />
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-1">
        {systemProviders.length > 0 && (
          <div>
            <p className="px-2 py-1 text-xs font-semibold text-[var(--text-muted)]">系统内置</p>
            {systemProviders.map((provider) => (
              <ProviderItem
                key={provider.provider_name}
                provider={provider}
                credential={credentialsByProvider.get(provider.provider_name)}
                isSelected={selectedProvider === provider.provider_name}
                onClick={() => onSelectProvider(provider.provider_name)}
                modelCount={provider.model_count ?? 0}
              />
            ))}
          </div>
        )}

        {customProviders.length > 0 && (
          <div>
            <p className="px-2 py-1 text-xs font-semibold text-[var(--text-muted)]">自定义</p>
            {customProviders.map((provider) => (
              <ProviderItem
                key={provider.provider_name}
                provider={provider}
                credential={credentialsByProvider.get(provider.provider_name)}
                isSelected={selectedProvider === provider.provider_name}
                onClick={() => onSelectProvider(provider.provider_name)}
                modelCount={provider.model_count ?? 0}
              />
            ))}
          </div>
        )}

        {filtered.length === 0 && (
          <p className="px-2 py-4 text-center text-xs text-[var(--text-muted)]">无匹配供应商</p>
        )}
      </div>
    </div>
  )
}
