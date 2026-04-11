'use client'

import { Search, X } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

export interface SearchInputProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  'value' | 'onChange'
> {
  value: string
  onValueChange: (value: string) => void
  onClear?: () => void
  showClearIcon?: boolean
  showSearchIcon?: boolean
}

const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(
  (
    {
      className,
      value,
      onValueChange,
      onClear,
      showClearIcon = true,
      showSearchIcon = true,
      placeholder,
      ...props
    },
    ref,
  ) => {
    const handleClear = () => {
      onValueChange('')
      onClear?.()
    }

    return (
      <div
        className={cn(
          'relative flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-transparent px-2 py-1.5',
          className,
        )}
      >
        {showSearchIcon && (
          <Search className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-subtle)]" />
        )}
        <input
          ref={ref}
          type="text"
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 bg-transparent text-base font-medium text-[var(--text-secondary)] outline-none placeholder:text-[var(--text-tertiary)]"
          style={{ paddingRight: showClearIcon && value ? '20px' : '0' }}
          {...props}
        />
        {showClearIcon && value && (
          <button
            type="button"
            onClick={handleClear}
            className="absolute right-[8px] flex-shrink-0 rounded-sm p-0.5 transition-colors hover:bg-[var(--surface-5)]"
          >
            <X className="h-3 w-3 text-[var(--text-tertiary)]" />
          </button>
        )}
      </div>
    )
  },
)

SearchInput.displayName = 'SearchInput'

export { SearchInput }
