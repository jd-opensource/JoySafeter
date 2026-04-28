import { STEP_SIZE } from '../lib/timeline-calculations'

interface TimelineScaleProps {
  traceDuration: number
  scaleWidth: number
  stepSize: number
}

export function TimelineScale({
  traceDuration,
  scaleWidth,
  stepSize,
}: TimelineScaleProps) {
  const numMarkers = Math.ceil(scaleWidth / STEP_SIZE) + 1

  return (
    <div className="mb-2 ml-2">
      <div className="relative mr-2 h-8" style={{ width: `${scaleWidth}px` }}>
        {Array.from({ length: numMarkers }).map((_, i) => {
          const timeValue = stepSize * i
          if (timeValue > traceDuration) return null

          return (
            <div
              key={i}
              className="absolute h-full border-l text-xs"
              style={{ left: `${i * STEP_SIZE}px` }}
            >
              <span
                className="absolute left-2 text-xs text-muted-foreground"
                title={`${timeValue.toFixed(2)}s`}
              >
                {timeValue.toFixed(2)}s
              </span>
            </div>
          )
        })}

        {Array.from({ length: numMarkers }).map((_, i) => {
          const timeValue = stepSize * i
          if (timeValue > traceDuration || i === 0) return null

          return (
            <div
              key={`grid-${i}`}
              className="pointer-events-none absolute h-full border-l border-border/30"
              style={{ left: `${i * STEP_SIZE}px` }}
            />
          )
        })}
      </div>
    </div>
  )
}
