import { forwardRef } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex select-none items-center justify-center gap-1.5 rounded-sm border font-semibold uppercase tracking-wide transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-router disabled:cursor-not-allowed disabled:opacity-40',
  {
    variants: {
      variant: {
        default: 'border-term-border bg-term-panel2 text-term-text hover:bg-term-grid',
        go: 'border-risk-green bg-risk-green/10 text-risk-green hover:bg-risk-green/25',
        nogo: 'border-risk-red bg-risk-red/10 text-risk-red hover:bg-risk-red/25',
        router: 'border-router bg-transparent text-router hover:bg-router/10',
        ghost: 'border-transparent text-term-dim hover:text-term-text hover:bg-term-grid',
      },
      size: {
        default: 'h-6 px-2 text-xxs',
        lg: 'h-9 px-4 text-sm',
        icon: 'h-6 w-6',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
)
Button.displayName = 'Button'
