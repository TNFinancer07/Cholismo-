/** Carte de sensibilité à la ruine + biais du survivant — GET /analyses/resilience (D-104).
 *
 *  ⚠️ CE N'EST PAS UNE PRÉDICTION. Chaque cellule suppose un taux de réussite ; le taux réel du
 *  LSR est INCONNU (c'est ce que la calibration mesure). D'où trois choix d'affichage qui ne sont
 *  pas décoratifs :
 *
 *  1. Le disclaimer du backend est rendu EN TÊTE, jamais en note de bas de tableau.
 *  2. Chaque cellule porte le badge `HYPOTHÈSE` — un tableau extrait de son contexte (capture
 *     d'écran, copie) doit rester lisible comme une hypothèse.
 *  3. PAS de dégradé continu. Un gradient se lit comme une mesure fine ; on affiche le nombre et
 *     une classe de risque à seuils nommés, forme + texte, jamais la seule couleur (§3).
 *
 *  LECTURE SEULE (§2.1). */
import { useEffect, useState } from 'react'
import { Panel } from '@/components/ui/panel'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'

interface Cell { win_rate: number; slippage_ticks: number; ruin_probability: number; status: string }
interface Sensitivity {
  kind: string; disclaimer: string
  axes: { slippage_ticks: number[]; win_rate: number[] }
  cells: Cell[][]
  model?: Record<string, unknown>
  account?: Record<string, unknown>
}
interface SurvivorBias {
  kind: string; status: string; n_reconciled: number; min_sample: number
  dd95_all: number | null; dd95_survivors: number | null; bias_r: number | null
  survival_rate: number | null; detail: string
}

/** Classes NOMMÉES, pas un gradient : « 8 % » et « 13 % » ne doivent pas se lire comme deux
 *  nuances d'un même continuum alors que la grille n'a que quatre points. */
export function classeRisque(p: number): { label: string; cls: string } {
  if (!Number.isFinite(p)) return { label: '—', cls: 'text-term-faint' }
  if (p >= 0.20) return { label: 'élevé', cls: 'text-bias-down font-bold' }
  if (p >= 0.05) return { label: 'notable', cls: 'text-gold' }
  return { label: 'faible', cls: 'text-term-dim' }
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(v) ? '—' : `${(v * 100).toFixed(1)} %`
}

function BiaisCard({ b }: { b: SurvivorBias }) {
  const refuse = b.status === 'NOT_ENOUGH_DATA'
  const nonMesurable = b.status === 'NO_RUIN_OBSERVED'
  return (
    <Panel code="RES2" title="Biais du survivant · DD95" block="analyses/resilience">
      <div className="flex flex-col gap-1 p-1.5 text-xs">
        <p className="text-xxs text-term-dim" data-testid="biais-detail">{b.detail}</p>
        {refuse ? (
          <p className="text-term-faint" data-testid="biais-refus">
            échantillon insuffisant — {b.n_reconciled}/{b.min_sample} R-multiples réconciliés
          </p>
        ) : (
          <table className="w-full">
            <tbody>
              <tr className="border-t border-term-border/50">
                <td className="py-0.5 pr-2 text-term-dim">DD95 · toutes trajectoires</td>
                <td className="py-0.5 tabular-nums text-term-text" data-testid="dd95-all">
                  {b.dd95_all === null ? '—' : `${b.dd95_all} R`}
                </td>
              </tr>
              <tr className="border-t border-term-border/50">
                <td className="py-0.5 pr-2 text-term-dim">DD95 · survivantes seules</td>
                <td className="py-0.5 tabular-nums text-term-faint" data-testid="dd95-surv">
                  {b.dd95_survivors === null ? '—' : `${b.dd95_survivors} R`}
                </td>
              </tr>
              <tr className="border-t border-term-border/50">
                <td className="py-0.5 pr-2 font-bold text-term-text">écart (le biais)</td>
                <td className="py-0.5 tabular-nums" data-testid="biais-ecart">
                  {b.bias_r === null ? (
                    <span className="text-term-faint" title={b.detail}>non mesurable</span>
                  ) : (
                    <span className="font-bold text-bias-down">{b.bias_r} R</span>
                  )}
                </td>
              </tr>
              <tr className="border-t border-term-border/50">
                <td className="py-0.5 pr-2 text-term-dim">taux de survie</td>
                <td className="py-0.5 tabular-nums text-term-dim" data-testid="survie">
                  {pct(b.survival_rate)}
                </td>
              </tr>
            </tbody>
          </table>
        )}
        {nonMesurable && (
          <p className="text-xxs text-term-faint" data-testid="biais-non-mesurable">
            aucune trajectoire n'atteint la limite — rien n'a été exclu, donc rien à biaiser
            (et non : un biais nul)
          </p>
        )}
      </div>
    </Panel>
  )
}

export function ResilienceView() {
  const [data, setData] = useState<{ sensitivity: Sensitivity; survivor_bias: SurvivorBias } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let vivant = true
    api.analysesResilience<{ sensitivity: Sensitivity; survivor_bias: SurvivorBias }>()
      .then((d) => { if (vivant) setData(d) })
      .catch((e) => { if (vivant) setErr(String(e)) })
    return () => { vivant = false }
  }, [])

  if (err) return <p className="p-2 text-xs text-bias-down">analyse indisponible — {err}</p>
  if (!data) return <p className="p-2 text-xs text-term-faint">chargement…</p>

  const s = data.sensitivity
  return (
    <div className="flex min-h-0 flex-col gap-2 p-2">
      {/* EN TÊTE, jamais en note de bas de tableau. */}
      <p className="border border-gold/50 bg-gold/5 p-1.5 text-xxs text-gold"
        data-testid="resilience-disclaimer">⚠ {s.disclaimer}</p>

      <Panel code="RES1" title="Sensibilité à la ruine · slippage × taux de réussite"
        block="analyses/resilience">
        <div className="overflow-x-auto p-1.5">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-xxs text-term-faint">
                <th className="text-left font-normal">slippage ↓ / réussite →</th>
                {s.axes.win_rate.map((wr) => (
                  <th key={wr} className="text-right font-normal tabular-nums">{pct(wr)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {s.cells.map((row) => (
                <tr key={row[0]?.slippage_ticks} className="border-t border-term-border/50">
                  <td className="py-0.5 pr-2 tabular-nums text-term-dim">
                    {row[0]?.slippage_ticks} tick
                  </td>
                  {row.map((c) => {
                    const k = classeRisque(c.ruin_probability)
                    return (
                      <td key={c.win_rate} className="py-0.5 text-right"
                        data-testid={`cell-${c.slippage_ticks}-${c.win_rate}`}>
                        <span className={cn('tabular-nums', k.cls)}>{pct(c.ruin_probability)}</span>
                        <span className="ml-1 text-xxs text-term-faint">{k.label}</span>
                        {/* Le badge suit la cellule, y compris hors contexte. */}
                        <span className="ml-1 rounded-sm border border-gold/40 px-0.5 text-xxs text-gold"
                          title="cellule conditionnelle à une hypothèse de taux de réussite">
                          {c.status === 'HYPOTHESIS' ? 'HYPOTHÈSE' : c.status}
                        </span>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <BiaisCard b={data.survivor_bias} />
    </div>
  )
}
