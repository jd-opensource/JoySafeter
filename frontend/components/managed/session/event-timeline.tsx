'use client'

import { useCallback, useMemo, useRef, useState } from "react"
import type { SessionEvent } from "@/types/managed"

interface EventTimelineProps {
  events: SessionEvent[]
  sessionStart: string
  selectedId?: string | null
  onSelect?: (event: SessionEvent) => void
}

function parseEventTime(event: SessionEvent, fallback: string): number {
  if (event.created_at) {
    const d = new Date(event.created_at).getTime()
    if (!isNaN(d)) return d
  }
  // Extract timestamp from UUIDv7 id (first 12 hex chars = 48-bit ms timestamp)
  const raw = (event.id || "").replace(/^evt_/, "").replace(/-/g, "")
  if (raw.length >= 12) {
    const ts = parseInt(raw.slice(0, 12), 16)
    if (ts > 1_000_000_000_000 && ts < 2_000_000_000_000) return ts
  }
  return new Date(fallback).getTime()
}

export function EventTimeline({ events, sessionStart, selectedId, onSelect }: EventTimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)

  const positions = useMemo(() => {
    if (events.length === 0) return []
    const times = events.map(e => parseEventTime(e, sessionStart))
    const minT = Math.min(...times)
    const maxT = Math.max(...times)
    const span = Math.max(maxT - minT, 1)
    return times.map(t => ((t - minT) / span) * 100)
  }, [events, sessionStart])

  const selectedIndex = useMemo(
    () => (selectedId ? events.findIndex(e => e.id === selectedId) : -1),
    [events, selectedId],
  )

  const findClosest = useCallback((clientX: number) => {
    if (!containerRef.current || positions.length === 0) return -1
    const rect = containerRef.current.getBoundingClientRect()
    const pct = ((clientX - rect.left) / rect.width) * 100

    let closest = 0
    let closestDist = Infinity
    for (let i = 0; i < positions.length; i++) {
      const dist = Math.abs(positions[i] - pct)
      if (dist < closestDist) {
        closestDist = dist
        closest = i
      }
    }
    return closest
  }, [positions])

  const handleClick = useCallback((e: React.MouseEvent) => {
    if (!onSelect) return
    const idx = findClosest(e.clientX)
    if (idx >= 0) onSelect(events[idx])
  }, [events, onSelect, findClosest])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const idx = findClosest(e.clientX)
    setHoverIndex(idx >= 0 ? idx : null)
  }, [findClosest])

  if (events.length === 0) return null

  return (
    <div className="relative">
      <div
        ref={containerRef}
        className="relative h-8 bg-secondary dark:bg-[#1e1e1e] rounded-md overflow-hidden cursor-pointer border border-border"
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {events.map((evt, i) => {
          const type = evt.type || evt.event_type || ""
          const color = getEventColor(type)
          const isSelected = i === selectedIndex
          const isHovered = i === hoverIndex
          const isKey = type === "user.message" || type === "agent.message" || type === "session.status_running" || type === "session.status_idle"
          const baseWidth = isKey ? 5 : 3

          return (
            <div
              key={evt.id || i}
              className="absolute top-[4px] bottom-[4px] rounded-sm"
              style={{
                left: `${positions[i]}%`,
                width: `${isSelected ? 7 : isHovered ? 6 : baseWidth}px`,
                backgroundColor: color,
                opacity: 1,
                boxShadow: isSelected ? `0 0 8px ${color}` : undefined,
                transform: `translateX(-50%)${isSelected ? " scaleY(1.1)" : ""}`,
                zIndex: isSelected ? 10 : isHovered ? 5 : isKey ? 3 : 1,
              }}
            />
          )
        })}
      </div>

      {hoverIndex !== null && events[hoverIndex] && (
        <div
          className="absolute -top-7 pointer-events-none text-[10px] bg-popover text-popover-foreground border border-border rounded px-1.5 py-0.5 whitespace-nowrap shadow-sm z-20"
          style={{
            left: `${positions[hoverIndex]}%`,
            transform: "translateX(-50%)",
          }}
        >
          {events[hoverIndex].type || events[hoverIndex].event_type || "event"}
        </div>
      )}
    </div>
  )
}

function getEventColor(type: string): string {
  // User events — red
  if (type === "user.message" || type === "user.interrupt" || type === "user.define_outcome") return "#ef4444"
  if (type.startsWith("user.")) return "#4b5563"

  // Agent events
  if (type === "agent.message") return "#2563eb"
  if (type === "agent.thinking" || type === "thinking") return "#ec4899"
  if (type === "agent.error") return "#dc2626"
  if (type.startsWith("agent.")) return "#374151"

  // Session status
  if (type === "session.status_running" || type === "session.thread_status_running") return "#10b981"
  if (type === "session.status_idle" || type === "session.thread_status_idle") return "#9ca3af"
  if (type === "session.status_rescheduled") return "#eab308"
  if (type === "session.error") return "#dc2626"
  if (type.startsWith("session.")) return "#6b7280"

  // Span / Model events — gray
  if (type.startsWith("span.")) return "#6b7280"

  return "#d4d4d8"
}
