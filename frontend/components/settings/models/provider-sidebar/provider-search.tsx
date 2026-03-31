'use client'

import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'

interface ProviderSearchProps {
  value: string
  onChange: (value: string) => void
}

export function ProviderSearch({ value, onChange }: ProviderSearchProps) {
  return (
    <div className="relative">
      <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="搜索供应商..."
        className="h-8 pl-8 text-sm"
      />
    </div>
  )
}
