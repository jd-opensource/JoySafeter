'use client'

import { useEffect, useRef } from 'react'

import { cn } from '@/lib/core/utils/cn'

type AuthBackgroundProps = {
  className?: string
  children?: React.ReactNode
}

const PARTICLE_COLOR = 'rgba(150, 150, 150, 0.3)'

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
    this.size = 1
  }

  update(
    mouse: { x: number; y: number; isActive: boolean },
    width: number,
    height: number
  ) {
    if (mouse.isActive) {
      const dx = this.x - mouse.x
      const dy = this.y - mouse.y
      const distance = Math.sqrt(dx * dx + dy * dy)
      const minDistance = 200
      if (distance < minDistance && distance > 0) {
        const force = (minDistance - distance) / minDistance
        const angle = Math.atan2(dy, dx)
        this.vx += Math.cos(angle) * force * 2
        this.vy += Math.sin(angle) * force * 2
      }
    }
    this.vy -= 0.05
    this.vx *= 0.98
    this.vy *= 0.98
    this.x += this.vx
    this.y += this.vy
    if (this.x < -10) this.x = width + 10
    if (this.x > width + 10) this.x = -10
    if (this.y < -10) this.y = height + 10
    if (this.y > height + 10) this.y = -10
    const dx = this.baseX - this.x
    const dy = this.baseY - this.y
    this.vx += dx * 0.001
    this.vy += dy * 0.001
  }

  draw(ctx: CanvasRenderingContext2D, particleColor: string) {
    ctx.fillStyle = particleColor
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

    const resizeCanvas = () => {
      width = window.innerWidth
      height = window.innerHeight
      canvas.width = width
      canvas.height = height
    }
    resizeCanvas()
    window.addEventListener('resize', resizeCanvas)

    // Create randomly distributed particles
    const particles: Particle[] = []
    const particleCount = Math.floor((width * height) / 3000) // Denser particles

    for (let i = 0; i < particleCount; i++) {
      const x = Math.random() * width
      const y = Math.random() * height
      particles.push(new Particle(x, y))
    }

    // Mouse tracking
    const mouse = {
      x: -1000,
      y: -1000,
      isActive: false,
    }

    const handleMouseMove = (e: MouseEvent) => {
      mouse.x = e.clientX
      mouse.y = e.clientY
      mouse.isActive = true
    }

    const handleMouseLeave = () => {
      mouse.isActive = false
    }

    canvas.addEventListener('mousemove', handleMouseMove)
    canvas.addEventListener('mouseleave', handleMouseLeave)

    // Animation loop
    let animationId: number

    const animate = () => {
      ctx.clearRect(0, 0, width, height)

      // Update and draw particles
      particles.forEach((particle) => {
        particle.update(mouse, width, height)
        particle.draw(ctx, PARTICLE_COLOR)
      })

      animationId = requestAnimationFrame(animate)
    }

    animate()

    return () => {
      window.removeEventListener('resize', resizeCanvas)
      canvas.removeEventListener('mousemove', handleMouseMove)
      canvas.removeEventListener('mouseleave', handleMouseLeave)
      cancelAnimationFrame(animationId)
    }
  }, [])

  return (
    <div className={cn('relative min-h-screen w-full overflow-hidden', className)}>
      {/* Pure white background */}
      <div
        className='fixed inset-0 h-full w-full bg-white'
        style={{ zIndex: 1 }}
      />

      {/* Particle canvas */}
      <canvas
        ref={canvasRef}
        className='fixed inset-0 h-full w-full'
        style={{ zIndex: 2 }}
      />

      <div className='relative z-20'>{children}</div>
    </div>
  )
}
