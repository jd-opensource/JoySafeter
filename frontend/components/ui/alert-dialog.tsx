'use client'

import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog'
import { X } from 'lucide-react'
import * as React from 'react'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const AlertDialog = AlertDialogPrimitive.Root

const AlertDialogTrigger = AlertDialogPrimitive.Trigger

const AlertDialogPortal = AlertDialogPrimitive.Portal

// Context for communication between overlay and content
const AlertDialogCloseContext = React.createContext<{
  triggerClose: () => void
} | null>(null)

const AlertDialogOverlay = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Overlay>
>(({ className, style, onClick, ...props }, ref) => {
  const [isStable, setIsStable] = React.useState(false)
  const closeContext = React.useContext(AlertDialogCloseContext)

  React.useEffect(() => {
    // Add a small delay before allowing overlay interactions to prevent rapid state changes
    const timer = setTimeout(() => setIsStable(true), 150)
    return () => clearTimeout(timer)
  }, [])

  return (
    <AlertDialogPrimitive.Overlay
      className={cn(
        'fixed inset-0 z-[10000150] bg-black/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
        className,
      )}
      style={{ backdropFilter: 'blur(4px)', ...style }}
      onClick={(e) => {
        // Only allow overlay clicks after component is stable
        if (!isStable) {
          e.preventDefault()
          return
        }
        // Only close if clicking directly on the overlay, not child elements
        if (e.target === e.currentTarget) {
          // Trigger close via context
          closeContext?.triggerClose()
        }
        // Call original onClick if provided
        onClick?.(e)
      }}
      {...props}
      ref={ref}
    />
  )
})
AlertDialogOverlay.displayName = AlertDialogPrimitive.Overlay.displayName

const AlertDialogContent = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content> & {
    hideCloseButton?: boolean
    variant?: 'default' | 'destructive'
  }
>(({ className, children, hideCloseButton = false, variant = 'default', ...props }, ref) => {
  const [isInteractionReady, setIsInteractionReady] = React.useState(false)
  const hiddenCancelRef = React.useRef<HTMLButtonElement>(null)

  React.useEffect(() => {
    // Prevent rapid interactions that can cause instability
    const timer = setTimeout(() => setIsInteractionReady(true), 100)
    return () => clearTimeout(timer)
  }, [])

  const closeContextValue = React.useMemo(
    () => ({
      triggerClose: () => hiddenCancelRef.current?.click(),
    }),
    [],
  )

  return (
    <AlertDialogPortal>
      <AlertDialogCloseContext.Provider value={closeContextValue}>
        <AlertDialogOverlay />
        <AlertDialogPrimitive.Content
          ref={ref}
          className={cn(
            // Base styles
            'fixed left-[50%] top-[50%] z-[10000151] grid w-full max-w-md translate-x-[-50%] translate-y-[-50%] gap-4 overflow-hidden rounded-2xl bg-[var(--surface-elevated)] px-6 py-6 shadow-2xl duration-200',
            // Animation
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%]',
            'data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%]',
            className,
          )}
          onPointerDown={(e) => {
            // Prevent event bubbling that might interfere with parent hover states
            e.stopPropagation()
          }}
          onPointerUp={(e) => {
            // Prevent event bubbling that might interfere with parent hover states
            e.stopPropagation()
          }}
          {...props}
        >
          {/* Top accent gradient bar */}
          <div
            className={cn(
              'absolute left-0 right-0 top-0 h-1',
              variant === 'destructive'
                ? 'bg-gradient-to-r from-[var(--status-error)] via-[var(--status-error)] to-[var(--status-error-hover)]'
                : 'bg-gradient-to-r from-[var(--brand-400)] via-[var(--gradient-brand-from)] to-[var(--brand-secondary)]',
            )}
          />
          {children}
          {!hideCloseButton && (
            <AlertDialogPrimitive.Cancel
              className="absolute right-5 top-5 flex h-6 w-6 items-center justify-center rounded-full border-0 bg-[var(--surface-3)] p-0 text-[var(--text-muted)] transition-all hover:bg-[var(--surface-5)] hover:text-[var(--text-secondary)] focus:outline-none disabled:pointer-events-none"
              disabled={!isInteractionReady}
              tabIndex={-1}
            >
              <X className="h-3.5 w-3.5" />
              <span className="sr-only">Close</span>
            </AlertDialogPrimitive.Cancel>
          )}
          {/* Hidden cancel button for overlay clicks */}
          <AlertDialogPrimitive.Cancel
            ref={hiddenCancelRef}
            style={{ display: 'none' }}
            tabIndex={-1}
            aria-hidden="true"
          />
        </AlertDialogPrimitive.Content>
      </AlertDialogCloseContext.Provider>
    </AlertDialogPortal>
  )
})
AlertDialogContent.displayName = AlertDialogPrimitive.Content.displayName

const AlertDialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn('flex flex-col space-y-1.5 text-left', className)} {...props} />
)
AlertDialogHeader.displayName = 'AlertDialogHeader'

const AlertDialogFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn('flex flex-row justify-end gap-3 pt-2', className)} {...props} />
)
AlertDialogFooter.displayName = 'AlertDialogFooter'

const AlertDialogTitle = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Title
    ref={ref}
    className={cn(
      'text-lg font-semibold tracking-tight text-[var(--text-primary)]',
      className,
    )}
    {...props}
  />
))
AlertDialogTitle.displayName = AlertDialogPrimitive.Title.displayName

const AlertDialogDescription = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Description
    ref={ref}
    className={cn('text-sm leading-relaxed text-[var(--text-tertiary)]', className)}
    {...props}
  />
))
AlertDialogDescription.displayName = AlertDialogPrimitive.Description.displayName

const AlertDialogAction = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Action>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Action>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Action
    ref={ref}
    className={cn(
      buttonVariants(),
      'min-w-[80px] font-medium shadow-sm transition-all hover:shadow-md',
      className,
    )}
    {...props}
  />
))
AlertDialogAction.displayName = AlertDialogPrimitive.Action.displayName

const AlertDialogCancel = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Cancel>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Cancel>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Cancel
    ref={ref}
    className={cn(
      buttonVariants({ variant: 'outline' }),
      'min-w-[80px] border-[var(--border)] bg-[var(--surface-elevated)] font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-1)] hover:text-[var(--text-primary)]',
      className,
    )}
    {...props}
  />
))
AlertDialogCancel.displayName = AlertDialogPrimitive.Cancel.displayName

export {
  AlertDialog,
  AlertDialogPortal,
  AlertDialogOverlay,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
}
