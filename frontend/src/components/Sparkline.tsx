/** Sparkline inline (lignée des terminaux financiers) — SVG maison, zéro dépendance. Rend
 *  l'historique CLIENT des valeurs du schéma reçues par SSE : aucune valeur inventée,
 *  buffer volatil, purement décoratif-informatif. */
import { useTerminal } from '@/store/terminal'
import { cn } from '@/lib/utils'

export function Sparkline({
  seriesKey, width = 72, height = 16, className, stroke = 'currentColor',
}: {
  seriesKey: string
  width?: number
  height?: number
  className?: string
  stroke?: string
}) {
  const points = useTerminal((s) => s.history[seriesKey])
  if (!points || points.length < 2) {
    return <span className={cn('inline-block text-xxs text-term-faint', className)}
      style={{ width, height, lineHeight: `${height}px` }}>·····</span>
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const step = width / (points.length - 1)
  const path = points
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(' ')
  const rising = points[points.length - 1] >= points[0]
  return (
    <svg width={width} height={height} className={cn('inline-block align-middle', className)}
      aria-label={`historique ${seriesKey}`} role="img">
      <path d={path} fill="none" strokeWidth="1"
        stroke={stroke === 'auto' ? (rising ? '#34d399' : '#f87171') : stroke}
        opacity="0.85" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
