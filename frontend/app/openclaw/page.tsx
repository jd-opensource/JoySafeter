'use client'

import { Settings2 } from 'lucide-react'

import { OpenClawManagement } from './components/OpenClawManagement'
import { OpenClawWebUI } from './components/OpenClawWebUI'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'

export default function OpenClawPage() {
  return (
    <div className="flex h-full flex-col overflow-hidden p-6 gap-4">
      <div className="flex shrink-0 items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[var(--text-primary)]">
            OpenClaw
          </h1>
        </div>

        <Sheet>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm" className="gap-2 shrink-0">
              <Settings2 className="h-4 w-4" />
              管理实例与设备
            </Button>
          </SheetTrigger>
          <SheetContent className="w-full sm:max-w-md overflow-y-auto">
            <SheetHeader className="mb-6">
              <SheetTitle>管理实例与设备</SheetTitle>
            </SheetHeader>
            <OpenClawManagement />
          </SheetContent>
        </Sheet>
      </div>

      <div className="min-h-0 flex-1">
        <OpenClawWebUI />
      </div>
    </div>
  )
}
