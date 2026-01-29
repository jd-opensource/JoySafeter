'use client'

import { Trash2, Plus } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'

interface KVListFieldProps {
  value: { key: string; value: string }[]
  onChange: (val: { key: string; value: string }[]) => void
}

export const KVListField: React.FC<KVListFieldProps> = ({ value, onChange }) => {
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
    <div className="space-y-2 border border-gray-200 rounded-xl p-3 bg-gray-50/30">
      {items.length === 0 && (
        <div className="text-[10px] text-gray-400 text-center py-2">
          {t('workspace.noParametersDefined')}
        </div>
      )}
      {items.map((item, index) => (
        <div key={index} className="flex gap-2 items-center">
          <Input
            value={item.key}
            onChange={(e) => handleChange(index, 'key', e.target.value)}
            placeholder={t('workspace.parameterName', { defaultValue: 'Name' })}
            className="h-8 text-xs bg-white"
          />
          <span className="text-gray-300 font-mono">:</span>
          <Input
            value={item.value}
            onChange={(e) => handleChange(index, 'value', e.target.value)}
            placeholder={t('workspace.parameterType', { defaultValue: 'Type' })}
            className="h-8 text-xs bg-white"
          />
          <Button
            variant="ghost"
            size="icon"
            onClick={() => handleRemove(index)}
            className="h-8 w-8 text-gray-400 hover:text-red-500"
          >
            <Trash2 size={12} />
          </Button>
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        onClick={handleAdd}
        className="w-full border-dashed text-gray-500 mt-1 h-8 text-xs"
      >
        <Plus size={12} /> {t('workspace.addParameter')}
      </Button>
    </div>
  )
}

