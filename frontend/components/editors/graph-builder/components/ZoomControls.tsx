'use client'

import { Maximize, Minus, Plus } from 'lucide-react'
import { useReactFlow } from 'reactflow'

import { Button } from '@/components/ui/button'

export function ZoomControls() {
  const { fitView, zoomIn, zoomOut } = useReactFlow()

  return (
    <div className="flex items-center gap-0.5">
      <Button
        variant="ghost"
        size="sm"
        className="h-6 w-6 p-0"
        onClick={() => fitView({ duration: 300 })}
        aria-label="Fit view"
      >
        <Maximize className="h-3 w-3" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-6 w-6 p-0"
        onClick={() => zoomOut({ duration: 200 })}
        aria-label="Zoom out"
      >
        <Minus className="h-3 w-3" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-6 w-6 p-0"
        onClick={() => zoomIn({ duration: 200 })}
        aria-label="Zoom in"
      >
        <Plus className="h-3 w-3" />
      </Button>
    </div>
  )
}
