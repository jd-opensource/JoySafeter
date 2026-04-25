import { describe, expect, it, vi } from 'vitest'

import { getContextMenuFlowPosition } from '../canvasContextMenuPosition'

describe('getContextMenuFlowPosition', () => {
  it('passes screen coordinates directly to React Flow', () => {
    const screenToFlowPosition = vi.fn(() => ({ x: 300, y: 180 }))

    const position = getContextMenuFlowPosition(screenToFlowPosition, 480, 260)

    expect(screenToFlowPosition).toHaveBeenCalledWith({ x: 480, y: 260 })
    expect(position).toEqual({ x: 300, y: 180 })
  })
})
