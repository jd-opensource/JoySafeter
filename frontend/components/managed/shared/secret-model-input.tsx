'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { MODEL_OPTIONS } from '@/lib/managed/secret-keys'
import { cn } from '@/lib/utils'

interface SecretModelInputProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}

export function SecretModelInput({
  value,
  onChange,
  placeholder,
  className,
}: SecretModelInputProps) {
  const [open, setOpen] = useState(false)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(
    () => () => {
      if (closeTimerRef.current) {
        clearTimeout(closeTimerRef.current)
      }
    },
    [],
  )

  const cancelPendingClose = () => {
    if (!closeTimerRef.current) return
    clearTimeout(closeTimerRef.current)
    closeTimerRef.current = null
  }

  const openDropdown = () => {
    cancelPendingClose()
    setOpen(true)
  }

  const closeDropdown = () => {
    cancelPendingClose()
    setOpen(false)
  }

  const scheduleCloseDropdown = () => {
    cancelPendingClose()
    closeTimerRef.current = setTimeout(() => {
      setOpen(false)
      closeTimerRef.current = null
    }, 120)
  }

  const filteredOptions = useMemo(() => {
    const keyword = value.trim().toLowerCase()
    if (!keyword) return MODEL_OPTIONS
    return MODEL_OPTIONS.filter((model) => model.toLowerCase().includes(keyword))
  }, [value])

  const showCustomValue = value.trim() && !MODEL_OPTIONS.includes(value.trim())

  const selectModel = (model: string) => {
    onChange(model)
    closeDropdown()
  }

  return (
    <div className={cn('relative flex-1', className)}>
      <Input
        value={value}
        onChange={(event) => {
          onChange(event.target.value)
          openDropdown()
        }}
        onFocus={openDropdown}
        onKeyDown={(event) => {
          if (event.key === 'Escape') closeDropdown()
        }}
        onBlur={scheduleCloseDropdown}
        placeholder={placeholder}
        className="pr-16 font-mono text-sm"
      />
      {value ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute right-8 top-1/2 h-7 w-7 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            onChange('')
            openDropdown()
          }}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      ) : null}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => {
          cancelPendingClose()
          setOpen((nextOpen) => !nextOpen)
        }}
      >
        <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} />
      </Button>

      {open ? (
        <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-top max-h-64 overflow-y-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-md">
          {showCustomValue ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left font-mono text-sm hover:bg-accent hover:text-accent-foreground"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectModel(value.trim())}
            >
              <span className="truncate">{value.trim()}</span>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">自定义</span>
            </button>
          ) : null}
          {filteredOptions.length > 0 ? (
            filteredOptions.map((model) => (
              <button
                key={model}
                type="button"
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left font-mono text-sm hover:bg-accent hover:text-accent-foreground"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selectModel(model)}
              >
                <span className="truncate">{model}</span>
                <Check
                  className={cn(
                    'ml-auto h-4 w-4 shrink-0',
                    value === model ? 'opacity-100' : 'opacity-0',
                  )}
                />
              </button>
            ))
          ) : !showCustomValue ? (
            <div className="px-2 py-2 text-sm text-muted-foreground">没有匹配的模型</div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
