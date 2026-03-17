'use client'

import { TooltipProvider } from '@/components/ui/tooltip'

interface WorkspaceRootLayoutProps {
  children: React.ReactNode
}
export default function WorkspaceRootLayout({ children }: WorkspaceRootLayoutProps) {
  return (
    <TooltipProvider delayDuration={600} skipDelayDuration={0}>
      {children}
    </TooltipProvider>
  )
}
