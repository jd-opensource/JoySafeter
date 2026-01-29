'use client'

import { Trash2, Plus } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'

interface StringArrayFieldProps {
  value: string[]
  onChange: (val: string[]) => void
  placeholder?: string
  description?: string
}

export const StringArrayField: React.FC<StringArrayFieldProps> = ({
  value,
  onChange,
  placeholder,
  description,
}) => {
  const { t } = useTranslation()
  const items = Array.isArray(value) ? value : []

  // Use translated placeholder if none provided
  const finalPlaceholder = placeholder || t('field.array.placeholder', { defaultValue: '输入选项名称' })

  const handleChange = (index: number, text: string) => {
    const newItems = [...items]
    newItems[index] = text
    onChange(newItems)
  }

  const handleAdd = () => onChange([...items, ''])
  const handleRemove = (index: number) => onChange(items.filter((_, i) => i !== index))

  return (
    <div className="space-y-2">
      <div className="space-y-2 border border-gray-200 rounded-xl p-3 bg-gray-50/30">
        {items.length === 0 && (
          <div className="text-[10px] text-gray-400 text-center py-2">
            {t('field.array.empty', { defaultValue: '暂无选项，点击下方按钮添加' })}
          </div>
        )}
        {items.map((item, index) => (
          <div key={index} className="flex gap-2 items-center">
            <div className="flex-1 flex items-center gap-2">
              <span className="text-[10px] text-gray-400 font-mono w-6 text-right">
                {index + 1}
              </span>
              <Input
                value={item}
                onChange={(e) => handleChange(index, e.target.value)}
                placeholder={finalPlaceholder}
                className="h-8 text-xs bg-white flex-1"
              />
            </div>
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
          <Plus size={12} className="mr-1" /> {t('field.array.addOption', { defaultValue: '添加选项' })}
        </Button>
      </div>
      {description && (
        <p className="text-[9px] text-gray-400 leading-tight italic">{description}</p>
      )}
    </div>
  )
}

