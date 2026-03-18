import * as React from 'react'

import { cn } from '@/lib/core/utils/cn'

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<'input'>>(
  ({ className, type, autoComplete = 'off', ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          'flex h-11 w-full rounded-[12px] border border-[var(--border)] bg-[var(--input-background)] px-3.5 py-2.5 text-[15px] text-[var(--text-primary)] ring-offset-background file:border-0 file:bg-transparent file:font-medium file:text-foreground file:text-sm placeholder:text-[var(--text-muted)] focus-visible:outline-none focus-visible:border-[var(--border-strong)] focus-visible:ring-2 focus-visible:ring-[color:rgba(36,56,77,0.12)] disabled:cursor-not-allowed disabled:opacity-50 md:text-sm transition-[border-color,background-color,box-shadow]',
          className
        )}
        ref={ref}
        autoComplete={autoComplete}
        autoCorrect='off'
        autoCapitalize='off'
        spellCheck='false'
        {...props}
      />
    )
  }
)
Input.displayName = 'Input'

export { Input }
