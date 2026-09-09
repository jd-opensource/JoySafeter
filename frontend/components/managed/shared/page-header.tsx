'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'

interface PageHeaderProps {
  title: string
  titleExtra?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  /**
   * Optional resource glyph. The caller passes a bare icon element; the tile
   * chrome and icon sizing are owned here so every page renders it identically.
   */
  icon?: ReactNode
  breadcrumb?: { label: string; to?: string; onClick?: () => void }[]
}

export function PageHeader({
  title,
  titleExtra,
  subtitle,
  action,
  icon,
  breadcrumb,
}: PageHeaderProps) {
  return (
    <div
      data-testid="page-header"
      className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"
    >
      <div className="min-w-0">
        {breadcrumb && (
          <nav className="mb-1 text-sm text-muted-foreground">
            {breadcrumb.map((crumb, i) => (
              <span key={i}>
                {i > 0 && <span className="mx-1.5">/</span>}
                {crumb.to ? (
                  <Link href={crumb.to} className="transition-colors hover:text-foreground">
                    {crumb.label}
                  </Link>
                ) : crumb.onClick ? (
                  <button
                    type="button"
                    onClick={crumb.onClick}
                    className="transition-colors hover:text-foreground"
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
        <div className="flex items-start gap-3">
          {icon && (
            <div
              data-testid="page-header-icon"
              className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted [&>svg]:size-5 [&>svg]:text-muted-foreground"
            >
              {icon}
            </div>
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
              {titleExtra}
            </div>
            {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
          </div>
        </div>
      </div>
      {action && (
        <div
          data-testid="page-header-action"
          className="w-full shrink-0 sm:w-auto [&>*]:w-full sm:[&>*]:w-auto"
        >
          {action}
        </div>
      )}
    </div>
  )
}
