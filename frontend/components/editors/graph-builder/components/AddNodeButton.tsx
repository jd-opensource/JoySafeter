'use client'

import { Plus } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useTranslation } from '@/lib/i18n'

import { AddNodePalette } from './AddNodePalette'

interface AddNodeButtonProps {
  onAddNode: (node: { type: string; label: string }) => void
}

export function AddNodeButton({ onAddNode }: AddNodeButtonProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="outline" className="h-7 gap-1.5 px-2.5">
          <Plus size={13} />
          <span>{t('agents.studio.addNode.button', { defaultValue: 'Add' })}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-0">
        <AddNodePalette
          onSelect={(node) => {
            onAddNode(node)
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
