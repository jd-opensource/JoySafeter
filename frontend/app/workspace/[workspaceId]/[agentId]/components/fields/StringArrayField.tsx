'use client'

import { Trash2, Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'

interface StringArrayFieldProps {
  value: string[]
  onChange: (val: string[]) => void
  placeholder?: string
  description?: string
}

export function StringArrayField({
  value,
  onChange,
  placeholder,
  description,
}: StringArrayFieldProps) {
  const { t } = useTranslation()
  const items = Array.isArray(value) ? value : []

  // Use translated placeholder if none provided
  const finalPlaceholder =
    placeholder || t('field.array.placeholder', { defaultValue: '输入选项名称' })

  const handleChange = (index: number, text: string) => {
    const newItems = [...items]
    newItems[index] = text
    onChange(newItems)
  }

  const handleAdd = () => onChange([...items, ''])
  const handleRemove = (index: number) => onChange(items.filter((_, i) => i !== index))

  return (
    <div className="space-y-2">
      <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--surface-2)]/30 p-3">
        {items.length === 0 && (
          <div className="py-2 text-center text-[10px] text-[var(--text-muted)]">
            {t('field.array.empty', { defaultValue: '暂无选项，点击下方按钮添加' })}
          </div>
        )}
        {items.map((item, index) => (
          <div key={index} className="flex items-center gap-2">
            <div className="flex flex-1 items-center gap-2">
              <span className="w-6 text-right font-mono text-[10px] text-[var(--text-muted)]">
                {index + 1}
              </span>
              <Input
                value={item}
                onChange={(e) => handleChange(index, e.target.value)}
                placeholder={finalPlaceholder}
                className="h-8 flex-1 bg-[var(--surface-elevated)] text-xs"
              />
            </div>
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
          <Plus size={12} className="mr-1" />{' '}
          {t('field.array.addOption', { defaultValue: '添加选项' })}
        </Button>
      </div>
      {description && (
        <p className="text-[9px] italic leading-tight text-[var(--text-muted)]">{description}</p>
      )}
    </div>
  )
}
