'use client'

import { useCallback, useState } from 'react'

export function useDropZone(onDrop?: (agentId: string) => void) {
  const [isDragOver, setIsDragOver] = useState(false)

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const agentId = e.dataTransfer.getData('agentId')
    if (agentId) {
      onDrop?.(agentId)
    }
  }, [onDrop])

  return { isDragOver, handleDragOver, handleDragLeave, handleDrop }
}
