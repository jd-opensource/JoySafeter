'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

/**
 * Main settings page - redirects to the default settings tab
 */
export default function SettingsPage() {
  const router = useRouter()
  const { workspaceId } = useCurrentWorkspace()

  useEffect(() => {
    if (workspaceId) {
      router.replace(`/settings/members/${workspaceId}`)
    } else {
      router.replace('/settings/models')
    }
  }, [workspaceId, router])

  return null
}
