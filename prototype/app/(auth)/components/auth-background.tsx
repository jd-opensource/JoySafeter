'use client'

import { useEffect, useRef } from 'react'

import { cn } from '@/lib/core/utils/cn'

type AuthBackgroundProps = {
  className?: string
  children?: React.ReactNode
}

const PARTICLE_COLOR = 'rgba(139, 92, 246, 0.45)'

class Particle {
  x: number
  y: number
  baseX: number
  baseY: number
  vx: number
  vy: number
  size: number

  constructor(x: number, y: number) {
    this.baseX = x
    this.baseY = y
    this.x = x
    this.y = y
    this.vx = 0
    this.vy = 0
    this.size = Math.random() * 1.2 + 0.4
  }

  update(mouse: { x: number; y: number; isActive: boolean }, width: number, height: number) {
    if (mouse.isActive) {
      const dx = this.x - mouse.x
      const dy = this.y - mouse.y
      const distance = Math.sqrt(dx * dx + dy * dy)
      const minDistance = 180
      if (distance < minDistance && distance > 0) {
        const force = (minDistance - distance) / minDistance
        const angle = Math.atan2(dy, dx)
        this.vx += Math.cos(angle) * force * 2.5
        this.vy += Math.sin(angle) * force * 2.5
      }
    }
    this.vy -= 0.04
    this.vx *= 0.97
    this.vy *= 0.97
    this.x += this.vx
    this.y += this.vy
    if (this.x < -10) this.x = width + 10
    if (this.x > width + 10) this.x = -10
    if (this.y < -10) this.y = height + 10
    if (this.y > height + 10) this.y = -10
    this.vx += (this.baseX - this.x) * 0.001
    this.vy += (this.baseY - this.y) * 0.001
  }

  draw(ctx: CanvasRenderingContext2D) {
    ctx.fillStyle = PARTICLE_COLOR
    ctx.beginPath()
    ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2)
    ctx.fill()
  }
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

    const particles: Particle[] = []
    const count = Math.floor((width * height) / 3500)
    for (let i = 0; i < count; i++) {
      particles.push(new Particle(Math.random() * width, Math.random() * height))
    }

    const mouse = { x: -1000, y: -1000, isActive: false }
    const handleMouseMove = (e: MouseEvent) => { mouse.x = e.clientX; mouse.y = e.clientY; mouse.isActive = true }
    const handleMouseLeave = () => { mouse.isActive = false }
    canvas.addEventListener('mousemove', handleMouseMove)
    canvas.addEventListener('mouseleave', handleMouseLeave)

    let animId: number
    const animate = () => {
      ctx.clearRect(0, 0, width, height)
      particles.forEach((p) => { p.update(mouse, width, height); p.draw(ctx) })
      animId = requestAnimationFrame(animate)
    }
    animate()

    return () => {
      window.removeEventListener('resize', resize)
      canvas.removeEventListener('mousemove', handleMouseMove)
      canvas.removeEventListener('mouseleave', handleMouseLeave)
      cancelAnimationFrame(animId)
    }
  }, [])

  return (
    <div className={cn('relative min-h-screen w-full overflow-hidden', className)}>
      {/* Deep space background */}
      <div
        className="fixed inset-0 h-full w-full"
        style={{
          zIndex: 1,
          background: '#0a0a0f',
          backgroundImage: `
            radial-gradient(ellipse 70vw 60vh at 80% 0%, rgba(139,92,246,0.25) 0%, transparent 60%),
            radial-gradient(ellipse 50vw 40vh at 15% 100%, rgba(79,70,229,0.18) 0%, transparent 55%)
          `,
        }}
      />

      {/* Particle canvas */}
      <canvas ref={canvasRef} className="fixed inset-0 h-full w-full" style={{ zIndex: 2 }} />

      <div className="relative z-20">{children}</div>
    </div>
  )
}
