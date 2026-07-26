/** Alerte TradeManifest (D-045 tranche 2) — overlay modal du signal LSR, HORS ContextSchema
 *  (contrat-pont documenté D-045, seule exception §1 avec les vues analytics).
 *
 *  §2.1 — PROPOSITION, jamais un ordre : Espace ENREGISTRE la validation (transition unique
 *  ARMED → LOCKED dans le store), rien ne part vers un courtier, et l'overlay le dit à l'écran.
 *
 *  Compte à rebours : base = `performance.now() − receivedAtMs` (réception SSE, horloge monotone
 *  locale — JAMAIS le timestamp backend vs Date.now(), cf. store/manifest.ts). La barre se vide
 *  via rAF ; le calcul repart du delta réel à chaque frame, donc un onglet mis en arrière-plan
 *  (rAF suspendu) n'étire pas le TTL : au retour, l'échéance vraie s'applique immédiatement.
 *
 *  Clavier — MODAL : listener en phase CAPTURE, les touches simples ne fuient jamais vers les
 *  raccourcis globaux (G/N/V/M… restent inertes pendant l'alerte ; les combinaisons
 *  Ctrl/Cmd/Alt du navigateur passent). ARMED : Espace = valider, Échap = refuser (démontage
 *  silencieux). LOCKED : TOUTE touche ignorée — la garde structurelle anti-double-envoi est la
 *  transition unique du store, le clavier n'est que la première ligne.
 *
 *  §3 — la direction n'est JAMAIS portée par la seule couleur : flèche + libellé massif
 *  « ACHAT · LONG » / « VENTE · SHORT » + badge texte. Fin de TTL (même LOCKED) ou Échap →
 *  démontage SILENCIEUX : un signal périmé n'est plus actionnable, il disparaît (fail-closed). */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useManifest, type ManifestAlert } from '@/store/manifest'

// Direction : teintes VIVES dédiées (distinctes des statuts de risque et des couleurs opérateur §3)
const BUY = { hex: '#22c55e', arrow: '▲', label: 'ACHAT · LONG' }
const SELL = { hex: '#ef4444', arrow: '▼', label: 'VENTE · SHORT' }

const fmt = (v: number) => v.toFixed(2)

function AlertCard({ alert }: { alert: ManifestAlert }) {
  const { manifest: m, receivedAtMs, status } = alert
  const dir = m.direction === 'BUY' ? BUY : SELL
  const barRef = useRef<HTMLDivElement>(null)
  const [leftDs, setLeftDs] = useState(Math.ceil(m.timeToLiveMs / 100))   // dixièmes affichés

  // Compte à rebours — delta monotone depuis la réception, jamais l'horloge backend.
  useEffect(() => {
    let raf = 0
    const step = () => {
      const left = m.timeToLiveMs - (performance.now() - receivedAtMs)
      if (left <= 0) {
        // Démontage silencieux (fail-closed). ARMED → TIMEOUT journalisé (l'humain n'a pas agi) ;
        // LOCKED → l'ACK est déjà dans l'event store, simple démontage.
        const s = useManifest.getState()
        if (s.alert?.status === 'LOCKED') s.clear()
        else s.resolve('TIMEOUT')
        return
      }
      if (barRef.current) barRef.current.style.width = `${(left / m.timeToLiveMs) * 100}%`
      setLeftDs(Math.ceil(left / 100))
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [m.timeToLiveMs, receivedAtMs])

  // Clavier modal — capture : rien ne fuit vers les raccourcis globaux pendant l'alerte.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return              // raccourcis navigateur : intacts
      e.preventDefault()
      e.stopImmediatePropagation()
      const s = useManifest.getState()
      if (s.alert === null || s.alert.status === 'LOCKED') return // figé : toute touche ignorée
      if (e.repeat) return                                        // Espace maintenu ≠ rafale
      if (e.code === 'Space') s.lock()                            // re-vérifie l'échéance (gel de thread)
      else if (e.key === 'Escape') s.resolve('REJECT_USER')       // refus journalisé, démontage silencieux
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  return (
    <div data-overlay="trade_manifest"
      className="fixed inset-0 z-50 grid place-items-center bg-black/60">
      <div className="w-[430px] border-2 bg-term-panel font-mono shadow-2xl"
        style={{ borderColor: dir.hex }}>
        {/* entête : direction en flèche + TEXTE massif (jamais la couleur seule §3) */}
        <div className="flex items-center justify-between px-3 py-2"
          style={{ background: `${dir.hex}1a` }}>
          <span className="text-2xl font-bold tracking-wide" style={{ color: dir.hex }}>
            {dir.arrow} {dir.label}
          </span>
          <span className="text-right text-xs text-term-dim">
            <span className="block text-base font-bold text-term-text">{m.instrument}</span>
            {m.risk.positionSize} contrat{m.risk.positionSize > 1 ? 's' : ''}
          </span>
        </div>

        {/* corps : stop & objectif MASSIFS, entrée en appui */}
        <div className="grid grid-cols-2 gap-px bg-term-border">
          <div className="bg-term-panel px-3 py-2 text-center">
            <div className="text-xxs text-term-faint">STOP</div>
            <div className="text-3xl font-bold tabular-nums" style={{ color: SELL.hex }}>
              {fmt(m.risk.stopLoss)}
            </div>
          </div>
          <div className="bg-term-panel px-3 py-2 text-center">
            <div className="text-xxs text-term-faint">OBJECTIF</div>
            <div className="text-3xl font-bold tabular-nums" style={{ color: BUY.hex }}>
              {fmt(m.risk.takeProfit)}
            </div>
          </div>
        </div>
        <div className="flex items-baseline justify-between border-t border-term-border px-3 py-1.5">
          <span className="text-xs text-term-dim">ENTRÉE {m.entry.type}</span>
          <span className="text-lg font-bold tabular-nums text-term-text">{fmt(m.entry.price)}</span>
        </div>
        <div className="truncate px-3 pb-1.5 text-xxs text-term-faint" title={m.reason}>{m.reason}</div>

        {/* barre TTL qui se vide + restant numérique */}
        <div className="h-1.5 w-full bg-term-panel2">
          <div ref={barRef} data-ttl-bar className="h-full"
            style={{ width: '100%', background: dir.hex }} />
        </div>

        {/* pied : état + affordances clavier + §2.1 en toutes lettres */}
        <div className="flex items-center justify-between px-3 py-1.5 text-xxs">
          {status === 'LOCKED' ? (
            <span className="font-bold text-router">✓ VALIDÉ — VERROUILLÉ</span>
          ) : (
            <span className="text-term-dim">
              <kbd className="rounded-sm border border-term-border px-1 font-bold text-router">ESPACE</kbd> valider ·{' '}
              <kbd className="rounded-sm border border-term-border px-1 font-bold text-router">ÉCHAP</kbd> refuser
            </span>
          )}
          <span className="tabular-nums text-term-faint">
            {(leftDs / 10).toFixed(1)}s · <span className="text-term-dim">AUCUN ORDRE ENVOYÉ</span>
          </span>
        </div>
      </div>
    </div>
  )
}

export function TradeAlertOverlay() {
  const alert = useManifest((s) => s.alert)
  if (alert === null) return null
  // key = id : une nouvelle alerte remonte des effets FRAIS (rAF + clavier), jamais d'état hérité
  return <AlertCard key={alert.manifest.id} alert={alert} />
}
