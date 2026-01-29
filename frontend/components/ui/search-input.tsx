'use client'

import { Search, X } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/core/utils/cn'

export interface SearchInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> {
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
    ref
  ) => {
    const handleClear = () => {
      onValueChange('')
      onClear?.()
    }

    return (
      <div
        className={cn(
          'relative flex items-center gap-[6px] rounded-[6px] border border-[var(--border)] bg-transparent px-[8px] py-[6px]',
          className
        )}
      >
        {showSearchIcon && (
          <Search className='h-[14px] w-[14px] flex-shrink-0 text-[var(--text-subtle)]' />
        )}
        <input
          ref={ref}
          type='text'
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          placeholder={placeholder}
          className='flex-1 bg-transparent text-[13px] font-medium text-[var(--text-secondary)] placeholder:text-[var(--text-tertiary)] outline-none'
          style={{ paddingRight: showClearIcon && value ? '20px' : '0' }}
          {...props}
        />
        {showClearIcon && value && (
          <button
            type='button'
            onClick={handleClear}
            className='absolute right-[8px] flex-shrink-0 rounded-[4px] p-[2px] transition-colors hover:bg-[var(--surface-5)]'
          >
            <X className='h-[12px] w-[12px] text-[var(--text-tertiary)]' />
          </button>
        )}
      </div>
    )
  }
)

SearchInput.displayName = 'SearchInput'

export { SearchInput }
