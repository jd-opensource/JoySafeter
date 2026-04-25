type FlowPosition = { x: number; y: number }

export function getContextMenuFlowPosition(
  screenToFlowPosition: (position: FlowPosition) => FlowPosition,
  clientX: number,
  clientY: number,
) {
  return screenToFlowPosition({ x: clientX, y: clientY })
}
