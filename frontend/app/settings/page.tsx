'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useWorkspaces } from '@/hooks/queries/workspaces'

/**
 * Main settings page - redirects to the default settings tab
 */
export default function SettingsPage() {
  const router = useRouter()
  const { data: workspaces = [] } = useWorkspaces()
  const workspaceId = workspaces[0]?.id ?? ''

  useEffect(() => {
    if (workspaceId) {
      router.replace(`/settings/members/${workspaceId}`)
    } else {
      router.replace('/settings/models')
    }
  }, [workspaceId, router])

  return null
}
