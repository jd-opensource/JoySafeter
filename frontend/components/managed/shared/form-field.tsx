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
