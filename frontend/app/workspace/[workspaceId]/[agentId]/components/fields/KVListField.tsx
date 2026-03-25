'use client'

import { Trash2, Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'

interface KVListFieldProps {
  value: { key: string; value: string }[]
  onChange: (val: { key: string; value: string }[]) => void
}

export function KVListField({ value, onChange }: KVListFieldProps) {
  const { t } = useTranslation()
  const items = Array.isArray(value) ? value : []

  const handleChange = (index: number, field: 'key' | 'value', text: string) => {
    const newItems = [...items]
    newItems[index] = { ...newItems[index], [field]: text }
    onChange(newItems)
  }

  const handleAdd = () => onChange([...items, { key: '', value: '' }])
  const handleRemove = (index: number) => onChange(items.filter((_, i) => i !== index))

  return (
    <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3">
      {items.length === 0 && (
        <div className="py-2 text-center text-[10px] text-[var(--text-muted)]">
          {t('workspace.noParametersDefined')}
        </div>
      )}
      {items.map((item, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            value={item.key}
            onChange={(e) => handleChange(index, 'key', e.target.value)}
            placeholder={t('workspace.parameterName', { defaultValue: 'Name' })}
            className="h-8 bg-[var(--surface-elevated)] text-xs"
          />
          <span className="font-mono text-[var(--text-subtle)]">:</span>
          <Input
            value={item.value}
            onChange={(e) => handleChange(index, 'value', e.target.value)}
            placeholder={t('workspace.parameterType', { defaultValue: 'Type' })}
            className="h-8 bg-[var(--surface-elevated)] text-xs"
          />
          <Button
            variant="ghost"
            size="icon"
            onClick={() => handleRemove(index)}
            className="h-8 w-8 text-[var(--text-muted)] hover:text-[var(--status-error)]"
          >
            <Trash2 size={12} />
          </Button>
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        onClick={handleAdd}
        className="mt-1 h-8 w-full border-dashed text-xs text-[var(--text-tertiary)]"
      >
        <Plus size={12} /> {t('workspace.addParameter')}
      </Button>
    </div>
  )
}
