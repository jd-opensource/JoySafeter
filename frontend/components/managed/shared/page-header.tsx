'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'

interface PageHeaderProps {
  title: string
  titleExtra?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  breadcrumb?: { label: string; to?: string; onClick?: () => void }[]
}

export function PageHeader({
  title,
  titleExtra,
  subtitle,
  action,
  breadcrumb,
}: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        {breadcrumb && (
          <nav className="text-sm text-muted-foreground mb-1">
            {breadcrumb.map((crumb, i) => (
              <span key={i}>
                {i > 0 && <span className="mx-1.5">/</span>}
                {crumb.to ? (
                  <Link
                    href={crumb.to}
                    className="hover:text-foreground transition-colors"
                  >
                    {crumb.label}
                  </Link>
                ) : crumb.onClick ? (
                  <button
                    type="button"
                    onClick={crumb.onClick}
                    className="hover:text-foreground transition-colors"
                  >
                    {crumb.label}
                  </button>
                ) : (
                  <span>{crumb.label}</span>
                )}
              </span>
            ))}
          </nav>
        )}
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
          {titleExtra}
        </div>
        {subtitle && (
          <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  )
}
