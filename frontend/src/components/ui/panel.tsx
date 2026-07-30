/** Panneau terminal — un panneau = un bloc du schéma (CLAUDE §1). L'entête porte le
 *  mnémonique (lignée des terminaux financiers) + le bloc source + le BADGE OPÉRATEUR.
 *  Attribution claire de chaque bloc (D-024) : S1 · SONY (rouge framboise) /
 *  S2 · YOUSSEF (jaune citron) / ROUTER (or) / SYSTÈME (neutre), dérivée de l'accent
 *  ou surchargée par `owner` pour les blocs mixtes (S1 + S2). La couleur n'est jamais
 *  seule : badge texte + liseré gauche. */
import { cn } from '@/lib/utils'

type Accent = 'sony' | 'youssef' | 'router' | 'none'

const OWNER_BADGES: Record<Accent, { label: string; cls: string } | null> = {
  sony: { label: 'S1 · SONY', cls: 'border-sony/70 text-sony' },
  youssef: { label: 'S2 · YOUSSEF', cls: 'border-youssef/70 text-youssef' },
  router: { label: 'ROUTER', cls: 'border-router/70 text-router' },
  none: { label: 'SYSTÈME', cls: 'border-term-border text-term-faint' },
}

/** Badge opérateur — exporté pour les entêtes hors-Panel (blotter, vues). */
export function OwnerBadge({ accent = 'none', owner }: { accent?: Accent; owner?: string }) {
  if (owner === 'S1 + S2') {
    return (
      <span className="inline-flex shrink-0 items-center gap-0.5 rounded-sm border border-term-border px-1 text-xxs font-bold tracking-wide"
        title="Bloc mixte : microstructure Sony + macro Youssef">
        <span className="text-sony">S1</span>
        <span className="text-term-faint">+</span>
        <span className="text-youssef">S2</span>
      </span>
    )
  }
  const badge = OWNER_BADGES[accent] ?? OWNER_BADGES.none
  if (!badge) return null
  return (
    <span className={cn('shrink-0 rounded-sm border px-1 text-xxs font-bold tracking-wide', badge.cls)}
      title={`bloc attribué : ${owner ?? badge.label}`}>
      {owner ?? badge.label}
    </span>
  )
}

export function Panel({
  code, title, block, accent, owner, className, children, right,
}: {
  code: string
  title: string
  block?: string
  accent?: Accent
  /** Surcharge du libellé opérateur (ex. « S1 + S2 » pour un bloc mixte). */
  owner?: string
  className?: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section
      className={cn(
        'flex min-h-0 flex-col border border-term-border border-l-2 bg-term-panel',
        accent === 'sony' && 'border-l-sony/80',
        accent === 'youssef' && 'border-l-youssef/80',
        accent === 'router' && 'border-router/70 border-l-router',
        (!accent || accent === 'none') && !owner && 'border-l-term-border',
        owner === 'S1 + S2' && 'border-l-transparent [border-image:linear-gradient(to_bottom,#f43f5e,#facc15)_1]',
        className,
      )}
      data-block={block}
    >
      <header
        className={cn(
          // `overflow-hidden` : CONFINEMENT pur (aucun effet quand la place existe). Le groupe de
          // droite est `shrink-0` — en colonne extrêmement étroite, un slot `right` long (ex: le
          // badge NT8 de C5) débordait de l'entête et pouvait empiéter sur le voisin (/devil D-051).
          'flex h-5 shrink-0 items-center justify-between gap-2 overflow-hidden border-b border-term-border bg-term-panel2 px-1.5',
          accent === 'sony' && 'border-b-sony/40',
          accent === 'youssef' && 'border-b-youssef/40',
          accent === 'router' && 'border-b-router/60',
        )}
      >
        {/* min-w-0 partout : un flex-child sans lui refuse de rétrécir sous la largeur
            de son contenu → l'entête élargirait la colonne entière (débordement
            horizontal en fenêtre étroite, trouvé par /devil). */}
        <div className="flex min-w-0 flex-1 items-baseline gap-1.5 overflow-hidden">
          <span
            className={cn(
              'shrink-0 text-xxs font-bold',
              accent === 'sony' && 'text-sony',
              accent === 'youssef' && 'text-youssef',
              accent === 'router' && 'text-router',
              (!accent || accent === 'none') && 'text-term-dim',
            )}
          >
            {code}
          </span>
          <h2 className="min-w-0 truncate text-xxs uppercase tracking-wider text-term-text">{title}</h2>
          {block && <span className="min-w-0 truncate text-xxs text-term-faint">{block}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {right}
          <OwnerBadge accent={accent ?? 'none'} owner={owner} />
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-1.5">{children}</div>
    </section>
  )
}
