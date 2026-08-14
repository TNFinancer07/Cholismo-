/** A3 — Score macro composite (`s2_macro_score`) — HONNÊTE, pas maquillé (CLAUDE §8.1).
 *  Non calibré : « NON CALIBRÉ », value=null, contribution live = 0, signal dégradé.
 *  Les intrants (coherence/tilt/gate) restent visibles pour aider la calibration. */
import { FlaskConical } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { fmtNum } from '@/lib/format'
import { useTerminal } from '@/store/terminal'

export function MacroScorePanel() {
  const macro = useTerminal((s) => s.s2_state?.s2_macro_score)

  return (
    <Panel code="A3" title="Score macro composite" block="s2_state.s2_macro_score" accent="youssef"
      right={macro?.calibrated
        ? <Badge variant="green">CALIBRÉ</Badge>
        : <Badge variant="yellow">NON CALIBRÉ</Badge>}>
      <div className="flex items-center justify-between">
        <span className="text-2xl font-black tabular-nums">
          {macro?.calibrated && macro.value !== null ? fmtNum(macro.value, 1) : '—'}
        </span>
        {!macro?.calibrated && (
          <span className="inline-flex items-center gap-1 text-xxs text-risk-yellow">
            <FlaskConical size={11} aria-hidden />
            contribution live = 0 · poids Macro → 0 · signal /80
          </span>
        )}
      </div>
      <div className="mt-1.5 grid grid-cols-3 gap-1.5 text-center">
        {([['coherence', macro?.coherence, '×0.50'], ['tilt', macro?.tilt, '×0.40'],
           ['gate', macro?.gate, '0.9–1.1']] as const).map(([label, value, note]) => (
          <div key={label} className="border border-term-border bg-term-panel2 py-1">
            <div className="text-xxs uppercase text-term-faint">{label} <span>{note}</span></div>
            <div className="tabular-nums text-term-dim">{value === null || value === undefined ? '—' : fmtNum(value, label === 'gate' ? 3 : 1)}</div>
          </div>
        ))}
      </div>
      <p className="mt-1 text-xxs text-term-faint">
        v1 provisional — calibration owner : Youssef · ne pilote rien avant validation
      </p>
    </Panel>
  )
}
