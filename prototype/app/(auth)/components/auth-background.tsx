'use client'

import { useEffect, useRef } from 'react'

import { cn } from '@/lib/core/utils/cn'

type AuthBackgroundProps = {
  className?: string
  children?: React.ReactNode
}

export default function AuthBackground({ className, children }: AuthBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    let width = window.innerWidth
    let height = window.innerHeight

    const resize = () => {
      width = window.innerWidth
      height = window.innerHeight
      canvas.width = width
      canvas.height = height
    }

    resize()
    window.addEventListener('resize', resize)

    let animationId = 0

    const draw = () => {
      ctx.clearRect(0, 0, width, height)

      ctx.strokeStyle = 'rgba(36, 56, 77, 0.08)'
      ctx.lineWidth = 1

      for (let x = 0; x < width; x += 72) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, height)
        ctx.stroke()
      }

      for (let y = 0; y < height; y += 72) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(width, y)
        ctx.stroke()
      }

      ctx.strokeStyle = 'rgba(36, 56, 77, 0.14)'
      ctx.beginPath()
      ctx.moveTo(width * 0.1, height * 0.82)
      ctx.bezierCurveTo(width * 0.32, height * 0.68, width * 0.52, height * 0.32, width * 0.88, height * 0.2)
      ctx.stroke()

      ctx.fillStyle = 'rgba(36, 56, 77, 0.18)'
      for (const [x, y] of [
        [width * 0.1, height * 0.82],
        [width * 0.32, height * 0.68],
        [width * 0.52, height * 0.32],
        [width * 0.88, height * 0.2],
      ]) {
        ctx.beginPath()
        ctx.arc(x, y, 4, 0, Math.PI * 2)
        ctx.fill()
      }

      animationId = requestAnimationFrame(draw)
    }

    draw()

    return () => {
      window.removeEventListener('resize', resize)
      cancelAnimationFrame(animationId)
    }
  }, [])

  return (
    <div className={cn('relative min-h-screen w-full overflow-hidden', className)}>
      <div
        className="fixed inset-0 h-full w-full"
        style={{
          zIndex: 1,
          background: '#f4f1ea',
          backgroundImage: `
            radial-gradient(ellipse 72vw 58vh at 100% 0%, rgba(36,56,77,0.10) 0%, transparent 60%),
            radial-gradient(ellipse 42vw 34vh at 14% 100%, rgba(126,143,161,0.14) 0%, transparent 58%),
            linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,255,255,0.08))
          `,
        }}
      />

      <div
        className="pointer-events-none fixed inset-y-0 left-[8%] hidden w-px lg:block"
        style={{ zIndex: 2, background: 'linear-gradient(180deg, transparent, rgba(36,56,77,0.22), transparent)' }}
      />
      <div
        className="pointer-events-none fixed inset-y-0 right-[11%] hidden w-px lg:block"
        style={{ zIndex: 2, background: 'linear-gradient(180deg, transparent, rgba(36,56,77,0.16), transparent)' }}
      />
      <canvas ref={canvasRef} className="fixed inset-0 h-full w-full opacity-70" style={{ zIndex: 2 }} />

      <div className="relative z-20">{children}</div>
    </div>
  )
}
