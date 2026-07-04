/** A2 — Matrice Bridgewater 5 dims × 6 axes, intensité signée. Encodage NON seulement
 *  par couleur : signe « + / − » incrusté + opacité proportionnelle (accessibilité). */
import { Panel } from '@/components/ui/panel'
import { MetaValue } from '@/components/MetaValue'
import { useTerminal } from '@/store/terminal'

const DIMS = ['Croissance', 'Inflation', 'Politique', 'Crédit', 'FX']
const AXES = ['US', 'EU', 'JP', 'CN', 'EM', 'CMD']

export function BridgewaterMatrix() {
  const matrixMeta = useTerminal((s) => s.s2_state?.bridgewater_matrix)
  const matrix = (matrixMeta?.value ?? null) as number[][] | null

  return (
    <Panel code="A2" title="Matrice Bridgewater" block="s2_state.bridgewater_matrix" accent="youssef">
      {!matrix ? (
        <MetaValue meta={matrixMeta} render={() => ''} />
      ) : (
        <table className="w-full border-collapse text-center text-xxs tabular-nums">
          <thead>
            <tr>
              <th />
              {AXES.map((a) => <th key={a} className="pb-0.5 font-semibold text-term-faint">{a}</th>)}
            </tr>
          </thead>
          <tbody>
            {matrix.slice(0, 5).map((row, i) => (
              <tr key={i}>
                <td className="pr-1 text-left uppercase text-term-dim">{DIMS[i]}</td>
                {row.slice(0, 6).map((cell, j) => {
                  const intensity = Math.min(1, Math.abs(cell))
                  const positive = cell > 0
                  return (
                    <td key={j} className="p-px">
                      <div
                        className="grid h-5 place-items-center border border-term-grid font-bold"
                        style={{
                          backgroundColor: positive
                            ? `rgba(52, 211, 153, ${0.08 + intensity * 0.5})`
                            : `rgba(248, 113, 113, ${0.08 + intensity * 0.5})`,
                        }}
                        title={`${DIMS[i]} × ${AXES[j]} : ${cell.toFixed(2)}`}
                      >
                        {/* signe incrusté : lisible sans percevoir la couleur */}
                        <span className="text-term-text/90">{cell === 0 ? '·' : positive ? '+' : '−'}{Math.round(intensity * 9)}</span>
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
