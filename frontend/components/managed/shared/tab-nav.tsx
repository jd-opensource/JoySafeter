'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { cn } from '@/lib/utils'

export interface TabNavItem {
  href: string
  label: string
}

/**
 * Underlined tab bar for resource detail shells. Owns the active-state styling
 * so every detail area renders the same tab chrome, and carries the trailing
 * spacing that separates it from the tab body.
 */
export function TabNav({ items, label }: { items: TabNavItem[]; label: string }) {
  const pathname = usePathname()

  return (
    <nav aria-label={label} className="mb-6 border-b border-border">
      <div className="flex gap-6 overflow-x-auto">
        {items.map((item) => {
          const active = pathname === item.href
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'relative whitespace-nowrap px-0.5 pb-3 text-sm font-medium transition-colors',
                active ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {item.label}
              {active ? <span className="absolute inset-x-0 -bottom-px h-0.5 bg-primary" /> : null}
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
