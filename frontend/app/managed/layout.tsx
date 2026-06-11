'use client'

import { useProjectContext } from '@/hooks/managed/use-project-context'

export default function ManagedLayout({ children }: { children: React.ReactNode }) {
  useProjectContext() // initializes project store on mount
  return <>{children}</>
}
