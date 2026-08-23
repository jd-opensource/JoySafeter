'use client'

import { getCredentialFieldGroups } from '@/lib/managed/credential-fields'
import { useTranslation } from '@/lib/i18n'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

interface CredentialFieldSelectProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  provider?: string
  protocol?: string
  disabled?: boolean
}

export function CredentialFieldSelect({
  value,
  onChange,
  placeholder,
  className,
  provider,
  protocol,
  disabled = false,
}: CredentialFieldSelectProps) {
  const { t } = useTranslation()
  const groups = getCredentialFieldGroups(provider, protocol)
  const visibleOptions = groups.flatMap((group) => group.keys)
  const showCurrentKey = !!value && !visibleOptions.includes(value)

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className={cn('flex-1 font-mono text-sm', className)} disabled={disabled}>
        <SelectValue placeholder={placeholder || t('managed.credentials.resources.selectKey')} />
      </SelectTrigger>
      <SelectContent>
        {groups.map((group) => (
          <SelectGroup key={group.id}>
            <SelectLabel className="flex items-center gap-2 px-2 py-2">
              <span
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white"
                style={{ backgroundColor: group.bgColor }}
              >
                {group.icon}
              </span>
              <span className="text-sm font-semibold text-foreground">
                {t(group.labelKey, { defaultValue: group.label })}
              </span>
            </SelectLabel>
            {group.keys.map((key, i) => {
              const isLast = i === group.keys.length - 1
              const prefix = isLast ? '└' : '├'
              return (
                <SelectItem key={key} value={key} className="pl-8 font-mono text-sm">
                  <span className="flex items-center gap-1.5">
                    <span className="text-xs text-muted-foreground/50">{prefix}</span>
                    {key}
                  </span>
                </SelectItem>
              )
            })}
          </SelectGroup>
        ))}
        {showCurrentKey && (
          <SelectGroup>
            <SelectLabel className="border-border/50 mt-1 flex items-center gap-2 border-t px-2 py-1.5 pt-1.5 text-xs font-semibold text-muted-foreground">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-gray-500 text-[10px] font-bold text-white">
                C
              </span>
              <span className="text-sm font-semibold text-foreground">
                {t('managed.credentials.resources.customKey')}
              </span>
            </SelectLabel>
            <SelectItem value={value} className="pl-8 font-mono text-sm">
              <span className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground/50">└</span>
                {value}
              </span>
            </SelectItem>
          </SelectGroup>
        )}
      </SelectContent>
    </Select>
  )
}
