'use client'

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useTranslation } from '@/lib/i18n'
import { filterSelectableSecretResources } from '@/lib/managed/secret-response-parsers'
import type { Secret } from '@/types/managed'

interface ServiceCredentialSelectProps {
  value: string
  onChange: (value: string) => void
  credentials: Secret[]
  loading?: boolean
  disabled?: boolean
  ariaLabel: string
}

function usableFieldCount(credential: Secret): number {
  return Object.keys(credential.data ?? {}).filter((field) => field.trim().length > 0).length
}

export function ServiceCredentialSelect({
  value,
  onChange,
  credentials,
  loading = false,
  disabled = false,
  ariaLabel,
}: ServiceCredentialSelectProps) {
  const { t } = useTranslation()
  const selectableCredentials = filterSelectableSecretResources(credentials)
  const showUnavailableValue =
    Boolean(value) && !credentials.some((item) => item.id === value)

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled || loading}>
      <SelectTrigger aria-label={ariaLabel} disabled={disabled || loading}>
        <SelectValue
          placeholder={
            loading ? t('common.loading') : t('managed.triggers.serviceCredentialPlaceholder')
          }
        />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {selectableCredentials.map((credential) => (
            <SelectItem key={credential.id} value={credential.id}>
              <span>{credential.name}</span>
              <span className="text-xs text-muted-foreground">
                {t('managed.triggers.credentialFieldCount', {
                  count: usableFieldCount(credential),
                })}
              </span>
            </SelectItem>
          ))}
          {showUnavailableValue ? (
            <SelectItem value={value}>
              <span>{value}</span>
              <span className="text-xs text-muted-foreground">
                {t('managed.triggers.serviceCredentialUnavailable')}
              </span>
            </SelectItem>
          ) : null}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
