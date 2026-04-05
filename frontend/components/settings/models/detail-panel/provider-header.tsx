'use client'

import { CheckCircle, Clock, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useValidateCredential, useDeleteCredential } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'
import type { ModelCredential, ModelProvider } from '@/types/models'

interface ProviderHeaderProps {
  provider: ModelProvider
  credential?: ModelCredential
  onEditCredential?: () => void
  onDeleteProvider?: () => void
}

function CredentialStatusBadge({ credential }: { credential?: ModelCredential }) {
  if (!credential) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-[var(--surface-3)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--text-muted)]" />
        Not configured
      </span>
    )
  }
  if (credential.is_valid) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-700">
        <CheckCircle className="h-3 w-3" />
        Valid
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">
      <XCircle className="h-3 w-3" />
      Invalid
    </span>
  )
}

export function ProviderHeader({ provider, credential, onEditCredential, onDeleteProvider }: ProviderHeaderProps) {
  const validateMutation = useValidateCredential()
  const deleteMutation = useDeleteCredential()
  const { toast } = useToast()

  const handleRevalidate = () => {
    if (credential?.id) {
      validateMutation.mutate(credential.id, {
        onSuccess: (data) => {
          toast({ title: data.is_valid ? 'Credential validation passed' : 'Credential validation failed' })
        },
        onError: (err) => {
          toast({
            variant: 'destructive',
            title: 'Validation request failed',
            description: err instanceof Error ? err.message : 'Please try again later',
          })
        },
      })
    }
  }

  const handleClearCredential = () => {
    if (!credential?.id) return
    deleteMutation.mutate(credential.id, {
      onSuccess: () => {
        toast({ title: 'Credential cleared' })
      },
      onError: (err) => {
        toast({
          variant: 'destructive',
          title: 'Failed to clear credential',
          description: err instanceof Error ? err.message : 'Please try again later',
        })
      },
    })
  }

  const isBuiltinProvider = provider.provider_type !== 'custom'

  const initials = provider.display_name.slice(0, 2).toUpperCase()

  return (
    <div className="border-b border-[var(--border-muted)] p-6">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--surface-3)] text-sm font-bold text-[var(--text-secondary)]">
            {initials}
          </div>
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">{provider.display_name}</h2>
            <p className="text-xs text-[var(--text-tertiary)]">{provider.provider_name}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {provider.provider_type === 'custom' && onDeleteProvider && (
            <Button variant="outline" size="sm" onClick={onDeleteProvider} className="text-red-600 hover:text-red-700">
              Delete
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onEditCredential}>
            {credential ? 'Edit Credential' : 'Configure Credential'}
          </Button>
        </div>
      </div>

      {/* Credential status card */}
      <div className="mt-4 rounded-lg border border-[var(--border-muted)] bg-[var(--surface-3)] p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">Credential Status</span>
            <CredentialStatusBadge credential={credential} />
          </div>
          {credential && (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={handleRevalidate}
                disabled={validateMutation.isPending}
              >
                Re-validate
              </Button>
              {isBuiltinProvider && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs text-red-600 hover:text-red-700"
                  onClick={handleClearCredential}
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending ? 'Clearing...' : 'Clear Credential'}
                </Button>
              )}
            </div>
          )}
        </div>

        {credential?.last_validated_at && (
          <div className="mt-1 flex items-center gap-1 text-xs text-[var(--text-tertiary)]">
            <Clock className="h-3 w-3" />
            Last validated: {new Date(credential.last_validated_at).toLocaleString()}
          </div>
        )}

        {credential?.validation_error && !credential.is_valid && (
          <p className="mt-1 text-xs text-red-600 line-clamp-2">{credential.validation_error}</p>
        )}
      </div>
    </div>
  )
}
