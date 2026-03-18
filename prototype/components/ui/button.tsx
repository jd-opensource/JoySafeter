import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from '@/lib/core/utils/cn'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[12px] border text-sm font-medium tracking-[0.01em] ring-offset-background transition-[background,border-color,color,box-shadow,transform] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default:
          'border-[color:color-mix(in_srgb,var(--brand-600)_72%,black_28%)] bg-[linear-gradient(180deg,var(--brand-400),var(--brand-500))] text-primary-foreground shadow-[0_14px_28px_rgba(36,56,77,0.14)] hover:-translate-y-px hover:bg-[linear-gradient(180deg,var(--brand-400),var(--brand-600))] hover:shadow-[0_18px_30px_rgba(36,56,77,0.16)]',
        destructive:
          'border-[color:color-mix(in_srgb,hsl(var(--destructive))_82%,black_18%)] bg-destructive text-destructive-foreground shadow-[0_10px_20px_rgba(156,68,56,0.14)] hover:-translate-y-px hover:bg-destructive/90',
        outline:
          'border-[var(--border-strong)] bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-[0_1px_0_rgba(255,255,255,0.7)_inset] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]',
        secondary:
          'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]',
        ghost:
          'border-transparent bg-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]',
        link: 'border-transparent bg-transparent px-0 text-[var(--brand-500)] hover:text-[var(--brand-600)] underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-8 rounded-[10px] px-3',
        lg: 'h-11 rounded-[14px] px-6',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    )
  }
)
Button.displayName = 'Button'

export { Button, buttonVariants }
