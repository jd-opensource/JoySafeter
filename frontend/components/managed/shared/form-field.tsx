'use client'

import type { ReactNode } from 'react'

import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

import { FieldHelp } from './field-help'

export function RequiredIndicator() {
  return (
    <span className="text-destructive" aria-hidden="true">
      *
    </span>
  )
}

export function OptionalIndicator({ children }: { children: ReactNode }) {
  return <span className="text-xs font-normal text-muted-foreground">{children}</span>
}

export function FormFieldLabel({
  htmlFor,
  children,
  required,
  optional,
  tooltip,
  className,
}: {
  htmlFor?: string
  children: ReactNode
  required?: boolean
  optional?: ReactNode
  tooltip?: string
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-1.5', className)}>
      <Label htmlFor={htmlFor} className="text-sm font-medium">
        {children}
      </Label>
      {required && <RequiredIndicator />}
      {optional && <OptionalIndicator>{optional}</OptionalIndicator>}
      {tooltip && <FieldHelp text={tooltip} />}
    </div>
  )
}

export function FormFieldError({ message, id }: { message?: string; id?: string }) {
  if (!message) return null
  return (
    <p id={id} className="text-xs text-destructive">
      {message}
    </p>
  )
}

export function FormSectionCard({
  title,
  description,
  children,
  className,
}: {
  title?: ReactNode
  description?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('rounded-xl border border-border bg-card/60 p-4 shadow-sm', className)}>
      {(title || description) && (
        <div className="mb-4 space-y-1">
          {title && <h3 className="text-sm font-semibold text-foreground">{title}</h3>}
          {description && <p className="text-xs leading-5 text-muted-foreground">{description}</p>}
        </div>
      )}
      <div className="space-y-4">{children}</div>
    </section>
  )
}

export function FormActionBar({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'sticky bottom-0 -mx-6 mt-6 flex justify-end gap-2 border-t border-border bg-background/95 px-6 py-4 backdrop-blur supports-[backdrop-filter]:bg-background/80',
        className,
      )}
    >
      {children}
    </div>
  )
}
