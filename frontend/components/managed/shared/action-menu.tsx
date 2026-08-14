'use client'

import { MoreVertical } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'

export interface MenuItem {
  label: string
  onClick: () => void
  destructive?: boolean
  icon?: ReactNode
  separator?: boolean
}

export function ActionMenu({
  items,
  disabled = false,
  ariaLabel,
}: {
  items: MenuItem[]
  disabled?: boolean
  ariaLabel?: string
}) {
  if (items.length === 0) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          disabled={disabled}
          aria-label={ariaLabel}
          onClick={(e) => e.stopPropagation()}
        >
          <MoreVertical className="h-4 w-4 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {items.map((item, i) => (
          <span key={item.label} className="contents">
            {item.separator && i > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem
              className={item.destructive ? 'text-red-600 focus:text-red-600' : undefined}
              onSelect={() => {
                item.onClick()
              }}
            >
              {item.icon && <span className="mr-2">{item.icon}</span>}
              {item.label}
            </DropdownMenuItem>
          </span>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
