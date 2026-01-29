'use client'

import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog'
import { X } from 'lucide-react'
import * as React from 'react'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/core/utils/cn'

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
        className
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
    []
  )

  return (
    <AlertDialogPortal>
      <AlertDialogCloseContext.Provider value={closeContextValue}>
        <AlertDialogOverlay />
        <AlertDialogPrimitive.Content
          ref={ref}
          className={cn(
            // Base styles
            'fixed top-[50%] left-[50%] z-[10000151] grid w-full max-w-md translate-x-[-50%] translate-y-[-50%] gap-4 rounded-2xl bg-white px-6 py-6 shadow-2xl duration-200 overflow-hidden',
            // Animation
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%]',
            'data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%]',
            // Dark mode
            'dark:bg-[#1a222b] dark:shadow-[0_25px_50px_-12px_rgba(0,0,0,0.5)]',
            className
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
              'absolute top-0 left-0 right-0 h-1',
              variant === 'destructive'
                ? 'bg-gradient-to-r from-red-500 via-rose-500 to-red-400'
                : 'bg-gradient-to-r from-[#8e4cfb] via-[#6f3dfa] to-[#33b4ff] dark:from-[#38bdf8] dark:via-[#0ea5e9] dark:to-[#06b6d4]'
            )}
          />
          {children}
          {!hideCloseButton && (
            <AlertDialogPrimitive.Cancel
              className='absolute top-5 right-5 h-6 w-6 flex items-center justify-center rounded-full border-0 bg-gray-100 p-0 text-gray-400 transition-all hover:bg-gray-200 hover:text-gray-600 focus:outline-none disabled:pointer-events-none dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600 dark:hover:text-gray-200'
              disabled={!isInteractionReady}
              tabIndex={-1}
            >
              <X className='h-3.5 w-3.5' />
              <span className='sr-only'>Close</span>
            </AlertDialogPrimitive.Cancel>
          )}
          {/* Hidden cancel button for overlay clicks */}
          <AlertDialogPrimitive.Cancel
            ref={hiddenCancelRef}
            style={{ display: 'none' }}
            tabIndex={-1}
            aria-hidden='true'
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
  <div
    className={cn('flex flex-row justify-end gap-3 pt-2', className)}
    {...props}
  />
)
AlertDialogFooter.displayName = 'AlertDialogFooter'

const AlertDialogTitle = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Title
    ref={ref}
    className={cn('font-semibold text-lg tracking-tight text-gray-900 dark:text-gray-100', className)}
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
    className={cn('text-sm text-gray-500 dark:text-gray-400 leading-relaxed', className)}
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
      className
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
      'min-w-[80px] font-medium border-gray-200 bg-white text-gray-700 hover:bg-gray-50 hover:text-gray-900 dark:border-gray-600 dark:bg-transparent dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-gray-100',
      className
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
