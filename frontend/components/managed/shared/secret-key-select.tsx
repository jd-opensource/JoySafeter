'use client'

import { getSecretKeyGroups } from '@/lib/managed/secret-keys'
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

interface SecretKeySelectProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  provider?: string
  protocol?: string
}

export function SecretKeySelect({ value, onChange, placeholder, className, provider, protocol }: SecretKeySelectProps) {
  const { t } = useTranslation()
  const groups = getSecretKeyGroups(provider, protocol)
  const visibleOptions = groups.flatMap((group) => group.keys)
  const showCurrentKey = !!value && !visibleOptions.includes(value)

  return (
    <Select
      value={value}
      onValueChange={onChange}
    >
      <SelectTrigger className={cn('flex-1 font-mono text-sm', className)}>
        <SelectValue placeholder={placeholder || t('managed.secrets.selectKey')} />
      </SelectTrigger>
      <SelectContent>
        {groups.map((group) => (
          <SelectGroup key={group.id}>
            <SelectLabel className="flex items-center gap-2 px-2 py-2">
              <span
                className="w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold text-white shrink-0"
                style={{ backgroundColor: group.bgColor }}
              >
                {group.icon}
              </span>
              <span className="text-sm font-semibold text-foreground">{t(group.labelKey, { defaultValue: group.label })}</span>
            </SelectLabel>
            {group.keys.map((key, i) => {
              const isLast = i === group.keys.length - 1
              const prefix = isLast ? '└' : '├'
              return (
                <SelectItem key={key} value={key} className="font-mono text-sm pl-8">
                  <span className="flex items-center gap-1.5">
                    <span className="text-muted-foreground/50 text-xs">{prefix}</span>
                    {key}
                  </span>
                </SelectItem>
              )
            })}
          </SelectGroup>
        ))}
        {showCurrentKey && (
          <SelectGroup>
            <SelectLabel className="flex items-center gap-2 px-2 py-1.5 text-xs font-semibold text-muted-foreground border-t border-border/50 mt-1 pt-1.5">
              <span className="w-5 h-5 rounded bg-gray-500 flex items-center justify-center text-[10px] font-bold text-white shrink-0">C</span>
              <span className="text-sm font-semibold text-foreground">{t('managed.secrets.customKey')}</span>
            </SelectLabel>
            <SelectItem value={value} className="font-mono text-sm pl-8">
              <span className="flex items-center gap-1.5">
                <span className="text-muted-foreground/50 text-xs">└</span>
                {value}
              </span>
            </SelectItem>
          </SelectGroup>
        )}
      </SelectContent>
    </Select>
  )
}
