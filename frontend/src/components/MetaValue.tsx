/** Helper de rendu FRESH / STALE / ABSENT (TASKS 1.4) — utilisé par TOUS les panneaux.
 *  STALE : valeur grisée + badge « périmé Xs ». ABSENT : « PAS DE DONNÉES », jamais un
 *  chiffre inventé (CLAUDE §2.3). Les flags de pathologie (retard, désync, contradiction)
 *  sont rendus visibles — pédigree de donnée façon ICE Data Services. */
import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Clock3, Unplug, GitCompareArrows } from 'lucide-react'
import { cn } from '@/lib/utils'
import { fmtAge } from '@/lib/format'
import { serverNow, useTerminal } from '@/store/terminal'
import type { MetaField } from '@/types/schema'

/** Flash de tick (lignée des terminaux financiers) : la valeur vire brièvement vert/rouge à la
 *  hausse/baisse. Purement visuel — appliqué uniquement aux valeurs FRESH. */
export function useTickFlash(value: unknown): string {
  const prev = useRef<number | null>(null)
  const [direction, setDirection] = useState<0 | 1 | -1>(0)
  useEffect(() => {
    if (typeof value !== 'number' || Number.isNaN(value)) return
    if (prev.current !== null && value !== prev.current) {
      setDirection(value > prev.current ? 1 : -1)
      const timer = window.setTimeout(() => setDirection(0), 450)
      prev.current = value
      return () => window.clearTimeout(timer)
    }
    prev.current = value
  }, [value])
  return direction === 1 ? 'text-risk-green transition-colors duration-500'
    : direction === -1 ? 'text-risk-red transition-colors duration-500'
    : 'transition-colors duration-500'
}

const FLAG_ICONS: Record<string, { icon: typeof Clock3; title: string }> = {
  LATE_FEED: { icon: Clock3, title: 'Flux en retard' },
  CLOCK_DESYNC: { icon: AlertTriangle, title: "Désynchronisation d'horloge source" },
  CROSS_SOURCE_DIVERGENT: { icon: GitCompareArrows, title: 'Sources contradictoires' },
  CROSSED_BOOK: { icon: GitCompareArrows, title: 'Carnet croisé (best bid ≥ best ask) — pathologie réelle' },
  MALFORMED: { icon: Unplug, title: 'Structure inexploitable — valeur retirée (fail-closed)' },
}

export function useDataAge(meta: MetaField | null | undefined): number | null {
  const nowTick = useTerminal((s) => s.nowTick)
  const clockOffset = useTerminal((s) => s.clockOffset)
  if (!meta?.last_update_ts) return null
  return Math.max(0, serverNow({ nowTick, clockOffset }) - meta.last_update_ts)
}

export function FlagIcons({ meta }: { meta: MetaField }) {
  if (!meta.flags?.length) return null
  return (
    <span className="inline-flex gap-0.5 align-middle">
      {meta.flags.map((flag) => {
        const spec = FLAG_ICONS[flag]
        if (!spec) return null
        const Icon = spec.icon
        return <Icon key={flag} size={10} className="text-risk-yellow" aria-label={spec.title} />
      })}
    </span>
  )
}

export function MetaValue({
  meta, render, className, unit,
}: {
  meta: MetaField | null | undefined
  render?: (v: unknown) => string
  className?: string
  unit?: string
}) {
  const age = useDataAge(meta)
  const flash = useTickFlash(meta?.freshness === 'FRESH' ? meta.value : null)
  if (!meta || meta.freshness === 'ABSENT' || meta.value === null) {
    return (
      <span className={cn('inline-flex items-center gap-1 text-absent absent-pulse', className)}
        title={meta ? `source: ${meta.source || '?'} — aucune donnée` : 'aucune donnée'}>
        <Unplug size={10} aria-hidden />
        <span className="tracking-tight">PAS DE DONNÉES</span>
      </span>
    )
  }
  const text = render ? render(meta.value) : String(meta.value)
  if (meta.freshness === 'STALE') {
    return (
      <span className={cn('inline-flex items-baseline gap-1', className)}
        title={`source: ${meta.source} — donnée périmée`}>
        <span className="text-stale opacity-70">{text}{unit && <span className="text-term-dim"> {unit}</span>}</span>
        <span className="rounded-sm border border-stale/50 px-0.5 text-xxs uppercase text-stale">
          périmé {fmtAge(age)}
        </span>
        <FlagIcons meta={meta} />
      </span>
    )
  }
  return (
    <span className={cn('inline-flex items-baseline gap-1', className)} title={`source: ${meta.source}`}>
      <span className={flash}>{text}{unit && <span className="text-term-dim"> {unit}</span>}</span>
      <FlagIcons meta={meta} />
    </span>
  )
}
