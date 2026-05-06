export const SCALE_WIDTH = 900
export const STEP_SIZE = 100

export const PREDEFINED_STEP_SIZES = [
  0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 35, 40, 45, 50, 100,
  150, 200, 250, 300, 350, 400, 450, 500,
]

export function calculateTimelineOffset(
  nodeStartTime: Date,
  traceStartTime: Date,
  totalScaleSpan: number,
  scaleWidth: number = SCALE_WIDTH,
): number {
  const timeFromStart = (nodeStartTime.getTime() - traceStartTime.getTime()) / 1000
  return (timeFromStart / totalScaleSpan) * scaleWidth
}

export function calculateTimelineWidth(
  duration: number,
  totalScaleSpan: number,
  scaleWidth: number = SCALE_WIDTH,
): number {
  return (duration / totalScaleSpan) * scaleWidth
}

export function calculateStepSize(traceDuration: number, scaleWidth: number = SCALE_WIDTH): number {
  const calculated = traceDuration / (scaleWidth / STEP_SIZE)
  return (
    PREDEFINED_STEP_SIZES.find((s) => s >= calculated) ??
    PREDEFINED_STEP_SIZES[PREDEFINED_STEP_SIZES.length - 1]
  )
}
