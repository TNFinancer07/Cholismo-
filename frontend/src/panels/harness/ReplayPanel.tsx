/** Contrôle du mode Replay (D-058) — play / pause / vitesse / seek.
 *
 *  Ce panneau pilote la SOURCE, jamais le moteur de décision : rejouer un tape ne prend aucune
 *  décision et ne passe aucun ordre (§2.1). Il ne s'affiche que si le terminal tourne réellement
 *  en replay — l'API répond 409 sinon, et afficher des boutons inertes serait pire que rien.
 *
 *  Le bandeau REJEU est délibérément voyant et non masquable. Un opérateur doit voir, sans rien
 *  ouvrir, que ce qui défile est un enregistrement : un replay qu'on prend pour du direct est le
 *  pire état possible de ce terminal. §3 transposé — le statut ne tient jamais à la seule
 *  couleur, il y a un mot, une icône et une position fixe.
 */
import { useCallback, useEffect, useState } from 'react'
import { History, Pause, Play, RotateCcw } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { ReplayState } from '@/types/replay'

const VITESSES = [0.25, 0.5, 1, 2, 5, 25, 100] as const

function positionPct(s: ReplayState): number {
  if (!s.total || s.total <= 0) return 0
  return Math.min(100, Math.max(0, (s.position / s.total) * 100))
}

export function ReplayPanel() {
  const [etat, setEtat] = useState<ReplayState | null>(null)
  const [indisponible, setIndisponible] = useState<string | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  const rafraichir = useCallback(async () => {
    try {
      setEtat(await api.replayState())
      setIndisponible(null)
    } catch (e) {
      // 409 = le terminal n'est pas en replay. C'est un ÉTAT, pas une panne : on le dit et on
      // cesse d'interroger plutôt que d'empiler des erreurs rouges dans la console.
      setIndisponible(e instanceof Error ? e.message : 'mode replay indisponible')
      setEtat(null)
    }
  }, [])

  useEffect(() => {
    void rafraichir()
    // Le rythme suit ce qu'on regarde : en lecture l'état bouge, à l'arrêt il ne bouge plus.
    const id = window.setInterval(() => { void rafraichir() }, etat?.playing ? 500 : 2000)
    return () => window.clearInterval(id)
  }, [rafraichir, etat?.playing])

  async function commander(payload: Parameters<typeof api.replayControl>[0]) {
    setErreur(null)
    try {
      setEtat(await api.replayControl(payload))
    } catch (e) {
      // Une commande refusée dit POURQUOI (le backend renvoie un motif) — jamais un échec muet.
      setErreur(e instanceof Error ? e.message : 'commande refusée')
    }
  }

  if (indisponible) {
    return (
      <Panel code="REPLAY" title="Replay — lecture d'un enregistrement" block="MarketDataSource (couture)">
        <p className="text-xs text-muted-foreground">{indisponible}</p>
      </Panel>
    )
  }
  if (!etat) {
    return (
      <Panel code="REPLAY" title="Replay — lecture d'un enregistrement" block="MarketDataSource (couture)">
        <p className="text-xs text-muted-foreground">chargement de l'état…</p>
      </Panel>
    )
  }

  const termine = etat.finished
  return (
    <Panel code="REPLAY" title="Replay — lecture d'un enregistrement" block="MarketDataSource (couture)">
      {/* Bandeau non masquable : forme + icône + mot, jamais la couleur seule (§3). */}
      <div
        data-testid="replay-banner"
        className="mb-2 flex items-center gap-2 border-l-4 border-amber-500 bg-amber-500/10 px-2 py-1"
      >
        <History className="h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden />
        <span className="font-mono text-[11px] font-bold tracking-wide text-amber-300">
          REJEU — ces prints sont un ENREGISTREMENT, pas le marché
        </span>
      </div>

      <p data-testid="replay-resume" className="mb-2 font-mono text-[11px] text-foreground">
        {etat.resume}
      </p>

      <div className="mb-2 flex items-center gap-1">
        <button
          type="button"
          data-testid="replay-toggle"
          disabled={termine}
          onClick={() => void commander({ action: etat.playing ? 'pause' : 'play' })}
          className={cn('flex items-center gap-1 border px-2 py-1 font-mono text-[11px]',
            termine ? 'cursor-not-allowed opacity-40' : 'hover:bg-accent')}
        >
          {etat.playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
          {etat.playing ? 'PAUSE' : 'LECTURE'}
        </button>
        <button
          type="button"
          data-testid="replay-restart"
          onClick={() => void commander({ action: 'restart' })}
          className="flex items-center gap-1 border px-2 py-1 font-mono text-[11px] hover:bg-accent"
        >
          <RotateCcw className="h-3 w-3" />
          REPRENDRE
        </button>
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-1">
        <span className="mr-1 font-mono text-[10px] text-muted-foreground">VITESSE</span>
        {VITESSES.map((v) => (
          <button
            key={v}
            type="button"
            data-testid={`replay-speed-${v}`}
            onClick={() => void commander({ action: 'speed', speed: v })}
            className={cn('border px-1.5 py-0.5 font-mono text-[10px]',
              etat.speed === v ? 'border-amber-500 bg-amber-500/20 text-amber-200'
                : 'hover:bg-accent')}
          >
            ×{v}
          </button>
        ))}
      </div>

      <label className="block">
        <span className="font-mono text-[10px] text-muted-foreground">
          POSITION {etat.position}/{etat.total ?? '?'}
        </span>
        <input
          type="range"
          data-testid="replay-seek"
          min={0}
          max={100}
          step={1}
          value={positionPct(etat)}
          onChange={(e) => void commander({
            action: 'seek', fraction: Number(e.target.value) / 100,
          })}
          className="w-full accent-amber-500"
        />
      </label>

      {etat.skipped > 0 && (
        <p data-testid="replay-skipped" className="mt-1 font-mono text-[10px] text-muted-foreground">
          {etat.skipped} ligne(s) du fichier écartée(s) —{' '}
          {Object.entries(etat.skipped_reasons).map(([m, n]) => `${n}× ${m}`).join(' · ')}
        </p>
      )}
      {erreur && (
        <p data-testid="replay-error" className="mt-1 font-mono text-[10px] text-destructive">
          {erreur}
        </p>
      )}
    </Panel>
  )
}
