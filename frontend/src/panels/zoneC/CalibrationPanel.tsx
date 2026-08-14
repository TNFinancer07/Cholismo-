/** C4 — Calibration (MVP) : DEUX jauges distinctes (quantitative + comportementale),
 *  N/60, sizing verrouillé 50 %, Sharpe courant (affiché seulement à 20+ trades),
 *  progression vers 50+. Les jauges viennent de projections indépendantes de l'event
 *  store — la validation séquentielle est impossible par construction (D-010). */
import { Lock, Unlock } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { fmtNum } from '@/lib/format'
import { asCalibration } from '@/lib/projections'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'

function Gauge({ label, pct, valid, detail }: {
  label: string; pct: number | null; valid: boolean; detail: React.ReactNode
}) {
  return (
    <div className="border border-term-border bg-term-panel2 p-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xxs font-bold uppercase tracking-wider text-term-dim">{label}</span>
        <Badge variant={valid ? 'green' : 'yellow'}>{valid ? 'VALIDE' : 'EN COURS'}</Badge>
      </div>
      <div className="mt-1 h-2.5 w-full border border-term-border bg-term-grid" role="progressbar"
        aria-valuenow={pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn('h-full', valid ? 'bg-risk-green/70' : 'bg-risk-yellow/50')}
          style={{ width: `${Math.min(100, pct ?? 0)}%` }} />
      </div>
      <div className="mt-1 space-y-0.5 text-xxs text-term-dim">{detail}</div>
    </div>
  )
}

export function CalibrationPanel() {
  const raw = useTerminal((s) => s.calibration)
  // Le serveur a répondu, mais avec un corps inexploitable : « chargement… » serait un mensonge
  // éternel. Attendre et être en panne ne se disent pas pareil (même règle qu'au canal lent).
  const broken = useTerminal((s) => s.projectionsBroken)
  // `if (!cal)` ne couvrait que l'absence TOTALE : un corps partiel (`{}`) est truthy, et
  // `cal.quantitative.progress_pct` levait — le panneau disparaissait sans un mot (bug D-053).
  // Même garde qu'à la frontière : une projection incomplète est une projection ABSENTE.
  const cal = asCalibration(raw)
  if (!cal) {
    return <Panel code="C4" title="Calibration" block="projections event store">
      {raw === null && !broken ? (
        <p className="text-term-faint">chargement…</p>
      ) : (
        // Distinguer « pas encore chargé » de « reçu mais inexploitable » : le second est une
        // panne à signaler, pas une attente. Aucune jauge fabriquée à 0 % (§3).
        <p className="text-absent" data-testid="c4-unavailable">
          PROJECTION INDISPONIBLE — réponse incomplète du serveur
        </p>
      )}
    </Panel>
  }
  const q = cal.quantitative
  const b = cal.behavioral

  return (
    <Panel code="C4" title="Calibration — 50+ trades, Sharpe > 0" block="projections event store"
      right={
        <span className={cn('inline-flex items-center gap-1 text-xxs font-bold',
          cal.sizing_locked ? 'text-risk-yellow' : 'text-risk-green')}
          title="Sizing verrouillé tant que les deux jauges ne sont pas validées ensemble">
          {cal.sizing_locked ? <Lock size={10} aria-hidden /> : <Unlock size={10} aria-hidden />}
          SIZING {cal.sizing_pct} %
        </span>
      }>
      <div className="grid grid-cols-2 gap-1.5">
        <Gauge label="Quantitatif" pct={q.progress_pct} valid={q.valid}
          detail={<>
            <div>trades réconciliés : <b className="text-term-text">{q.n_trades}</b> / {q.window} (cible {q.target}+)</div>
            <div>Sharpe : {q.sharpe_displayable
              ? <b className={cn(q.sharpe !== null && q.sharpe > 0 ? 'text-risk-green' : 'text-risk-red')}>{fmtNum(q.sharpe, 3)}</b>
              : <span title="Result score affiché après 20+ trades seulement (CLAUDE §2.7)">N/A (&lt; {cal.sharpe.min_trades} trades)</span>}
            </div>
          </>} />
        <Gauge label="Comportemental" pct={b.selfcheck_rate_pct !== null && b.recon_rate_pct !== null
            ? (b.selfcheck_rate_pct + b.recon_rate_pct) / 2 : 0}
          valid={b.valid}
          detail={<>
            <div>GO avec self-check : <b className="text-term-text">{b.selfcheck_rate_pct ?? '—'} %</b></div>
            <div>GO réconciliés : <b className="text-term-text">{b.recon_rate_pct ?? '—'} %</b></div>
            <div>timeouts C3 : {b.timeouts} · décisions : {b.n_decisions}</div>
          </>} />
      </div>
      <p className="mt-1 text-xxs text-term-faint">
        process score ≠ result score — jamais consolidés (CLAUDE §2.7)
      </p>
    </Panel>
  )
}
