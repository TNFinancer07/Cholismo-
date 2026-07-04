import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-sm border px-1.5 py-0 text-xxs font-semibold uppercase tracking-wide',
  {
    variants: {
      variant: {
        default: 'border-term-border text-term-dim',
        sony: 'border-sony/60 text-sony',
        youssef: 'border-youssef/60 text-youssef',
        router: 'border-router text-router',
        green: 'border-risk-green/60 text-risk-green',
        yellow: 'border-risk-yellow/60 text-risk-yellow',
        red: 'border-risk-red/60 text-risk-red',
        stale: 'border-stale/50 text-stale',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export function Badge({ className, variant, ...props }:
  React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
