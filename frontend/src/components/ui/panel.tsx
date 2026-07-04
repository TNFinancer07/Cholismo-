/** Panneau terminal — un panneau = un bloc du schéma (CLAUDE §1). L'entête porte le
 *  mnémonique (façon Bloomberg) + le bloc source + la pastille opérateur. */
import { cn } from '@/lib/utils'

export function Panel({
  code, title, block, accent, className, children, right,
}: {
  code: string
  title: string
  block?: string
  accent?: 'sony' | 'youssef' | 'router' | 'none'
  className?: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section
      className={cn(
        'flex min-h-0 flex-col border border-term-border bg-term-panel',
        accent === 'router' && 'border-router/70',
        className,
      )}
      data-block={block}
    >
      <header
        className={cn(
          'flex h-5 shrink-0 items-center justify-between gap-2 border-b border-term-border bg-term-panel2 px-1.5',
          accent === 'sony' && 'border-b-sony/40',
          accent === 'youssef' && 'border-b-youssef/40',
          accent === 'router' && 'border-b-router/60',
        )}
      >
        <div className="flex items-baseline gap-1.5 overflow-hidden">
          <span
            className={cn(
              'text-xxs font-bold',
              accent === 'sony' && 'text-sony',
              accent === 'youssef' && 'text-youssef',
              accent === 'router' && 'text-router',
              (!accent || accent === 'none') && 'text-term-dim',
            )}
          >
            {code}
          </span>
          <h2 className="truncate text-xxs uppercase tracking-wider text-term-text">{title}</h2>
          {block && <span className="truncate text-xxs text-term-faint">{block}</span>}
        </div>
        {right}
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-1.5">{children}</div>
    </section>
  )
}
