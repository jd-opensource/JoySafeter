'use client'

import { PanelLeft } from 'lucide-react'
import { useCallback, useRef } from 'react'


import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { MIN_SIDEBAR_WIDTH, useSidebarStore } from '@/stores/sidebar/store'

import { OpenClawManagement } from './OpenClawManagement'

export function Sidebar() {
  const { t } = useTranslation()

  const sidebarRef = useRef<HTMLElement>(null)

  const isCollapsed = useSidebarStore((state) => state.isCollapsed)
  const setIsCollapsed = useSidebarStore((state) => state.setIsCollapsed)
  const sidebarWidth = useSidebarStore((state) => state.sidebarWidth)
  const setSidebarWidth = useSidebarStore((state) => state.setSidebarWidth)
  const isAppSidebarCollapsed = useSidebarStore((state) => state.isAppSidebarCollapsed)

  const handleToggleCollapse = useCallback(() => {
    setIsCollapsed(!isCollapsed)
  }, [isCollapsed, setIsCollapsed])

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()

      const startX = e.clientX
      const startWidth = sidebarWidth

      const handleMouseMove = (mouseMoveEvent: MouseEvent) => {
        const delta = mouseMoveEvent.clientX - startX
        const newWidth = Math.max(MIN_SIDEBAR_WIDTH, startWidth + delta)
        const maxWidth = window.innerWidth * 0.4 // Allow up to 40% of screen width
        setSidebarWidth(Math.min(newWidth, maxWidth))
      }

      const handleMouseUp = () => {
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
        document.body.style.cursor = 'default'
      }

      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = 'col-resize'
    },
    [sidebarWidth, setSidebarWidth],
  )

  if (isCollapsed) {
    return (
      <div
        className="fixed top-[14px] z-10 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 transition-all duration-300"
        style={{
          left: isAppSidebarCollapsed ? 'calc(var(--sidebar-width-collapsed) + 14px)' : 'calc(var(--sidebar-width) + 14px)',
        }}
      >
        <div className="flex items-center gap-1.5">
          <h2 className="truncate text-base font-medium text-[var(--text-primary)]">OpenClaw</h2>
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="flex items-center justify-center rounded-sm p-[4px] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={handleToggleCollapse}
                  aria-label="Expand sidebar"
                >
                  <PanelLeft className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
                </button>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                sideOffset={4}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-sm font-medium text-[var(--text-primary)] shadow-lg"
              >
                {t('sidebar.expand')}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>
    )
  }

  return (
    <aside
      ref={sidebarRef}
      className={cn(
        'fixed inset-y-0 overflow-hidden border-r border-[var(--border)] bg-[var(--surface-2)] shadow-[2px_0_8px_rgba(0,0,0,0.05)] transition-all duration-300',
        isCollapsed ? 'pointer-events-none z-0' : 'z-10',
      )}
      style={{
        left: isCollapsed ? '-1000px' : isAppSidebarCollapsed ? 'var(--sidebar-width-collapsed)' : 'var(--sidebar-width)',
        width: isCollapsed ? '0px' : `${sidebarWidth}px`,
        opacity: isCollapsed ? 0 : 1,
        visibility: isCollapsed ? 'hidden' : 'visible',
        transition: 'left 0.3s ease, width 0.3s ease, opacity 0.3s ease',
      }}
      aria-label="OpenClaw sidebar"
    >
      <div className="flex h-full flex-col pt-[14px]">
        {/* Header */}
        <div className="flex-shrink-0 border-b border-[var(--border)] px-[14px] pb-[10px]">
          <div className="flex items-center justify-between gap-1.5">
            <h2 className="truncate text-base font-semibold text-[var(--text-primary)]">
              OpenClaw
            </h2>

            <TooltipProvider delayDuration={100}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="flex items-center justify-center rounded-sm p-[4px] transition-colors hover:bg-[var(--surface-5)]"
                    onClick={handleToggleCollapse}
                    aria-label="Collapse sidebar"
                  >
                    <PanelLeft className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
                  </button>
                </TooltipTrigger>
                <TooltipContent
                  side="bottom"
                  sideOffset={4}
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-sm font-medium text-[var(--text-primary)] shadow-lg"
                >
                  {t('sidebar.collapse')}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-[14px] py-[10px]">
          <OpenClawManagement />
        </div>
      </div>

      {/* Resize Handle */}
      <div
        className="hover:bg-[var(--brand-500)] absolute inset-y-0 right-0 w-[4px] cursor-col-resize transition-colors active:bg-[var(--brand-500)]"
        onMouseDown={handleMouseDown}
      />
    </aside>
  )
}
