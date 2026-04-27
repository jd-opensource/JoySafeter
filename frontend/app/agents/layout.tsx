'use client'

import { useEffect } from 'react'
import { useSidebarStore } from '@/stores/sidebar/store'

export default function AgentsLayout({ children }: { children: React.ReactNode }) {
  const setIsCollapsed = useSidebarStore((state) => state.setIsCollapsed)

  useEffect(() => {
    setIsCollapsed(true)

    return () => {
      setIsCollapsed(false)
    }
  }, [setIsCollapsed])

  return <>{children}</>
}
