/** Risque VERT/JAUNE/ROUGE — JAMAIS encodé par la seule couleur (CLAUDE §3) :
 *  forme distincte (● cercle / ▲ triangle / ⬢ octogone) + icône + libellé. */
import { CheckCircle2, AlertTriangle, OctagonX } from 'lucide-react'
import { cn } from '@/lib/utils'

export type RiskLevel = 'VERT' | 'JAUNE' | 'ROUGE'

const SPEC: Record<RiskLevel, { icon: typeof CheckCircle2; cls: string; shape: string }> = {
  VERT: { icon: CheckCircle2, cls: 'text-risk-green', shape: '●' },
  JAUNE: { icon: AlertTriangle, cls: 'text-risk-yellow', shape: '▲' },
  ROUGE: { icon: OctagonX, cls: 'text-risk-red', shape: '⬢' },
}

export function RiskGlyph({ level, label, size = 12, className }: {
  level: RiskLevel
  label?: string
  size?: number
  className?: string
}) {
  const { icon: Icon, cls } = SPEC[level]
  return (
    <span className={cn('inline-flex items-center gap-1', cls, className)} role="status"
      aria-label={`risque ${level}${label ? ` — ${label}` : ''}`}>
      <Icon size={size} aria-hidden />
      <span className="text-xxs font-bold">{label ?? level}</span>
    </span>
  )
}
