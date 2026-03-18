import * as React from 'react'

import { cn } from '@/lib/core/utils/cn'

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<'textarea'>>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          'flex min-h-[110px] w-full rounded-[14px] border border-[var(--border)] bg-[var(--input-background)] px-3.5 py-3 text-[15px] text-[var(--text-primary)] ring-offset-background placeholder:text-[var(--text-muted)] focus-visible:outline-none focus-visible:border-[var(--border-strong)] focus-visible:ring-2 focus-visible:ring-[color:rgba(36,56,77,0.12)] disabled:cursor-not-allowed disabled:opacity-50 md:text-sm transition-[border-color,background-color,box-shadow]',
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Textarea.displayName = 'Textarea'

export { Textarea }
