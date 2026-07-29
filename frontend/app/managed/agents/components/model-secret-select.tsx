'use client'

import { SearchableAgentConfigSelect } from './searchable-agent-config-select'

export interface ModelSecretOption {
  name: string
}

interface ModelSecretSelectProps {
  value: string
  secrets: ModelSecretOption[]
  placeholder: string
  noneLabel: string
  searchPlaceholder: string
  emptyText: string
  createLabel: string
  clearSearchLabel: string
  onChange: (value: string) => void
  onCreate: () => void
}

export function ModelSecretSelect({
  value,
  secrets,
  placeholder,
  noneLabel,
  searchPlaceholder,
  emptyText,
  createLabel,
  clearSearchLabel,
  onChange,
  onCreate,
}: ModelSecretSelectProps) {
  return (
    <SearchableAgentConfigSelect
      value={value}
      options={secrets.map((secret) => ({ value: secret.name, label: secret.name }))}
      placeholder={placeholder}
      noneLabel={noneLabel}
      searchPlaceholder={searchPlaceholder}
      emptyText={emptyText}
      createLabel={createLabel}
      clearSearchLabel={clearSearchLabel}
      onChange={onChange}
      onCreate={onCreate}
    />
  )
}
