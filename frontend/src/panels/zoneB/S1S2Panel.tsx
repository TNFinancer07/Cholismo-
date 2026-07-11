/** B1 — États S1 / S2 côte à côte (`s1_state` rouge / `s2_state` jaune).
 *  S1 sur canal rapide, S2 sur canal lent — les âges divergent, c'est voulu. */
import { Panel } from '@/components/ui/panel'
import { MetaValue } from '@/components/MetaValue'
import { Sparkline } from '@/components/Sparkline'
import { fmtNum, fmtSigned } from '@/lib/format'
import { useTerminal } from '@/store/terminal'
import { cn } from '@/lib/utils'

function Row({ label, children, alert }: { label: string; children: React.ReactNode; alert?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-term-grid py-0.5 last:border-0">
      <span className={cn('text-xxs uppercase text-term-dim', alert && 'text-risk-red')}>{label}</span>
      <span className="tabular-nums">{children}</span>
    </div>
  )
}

export function S1S2Panel() {
  const s1 = useTerminal((s) => s.s1_state)
  const s2 = useTerminal((s) => s.s2_state)
  const chopCrit = (s1?.chop.value ?? 0) >= 61.8

  return (
    <Panel code="B1" title="États S1 · S2" block="s1_state / s2_state" owner="S1 + S2">
      <div className="grid grid-cols-2 gap-2">
        <div className="border-l-2 border-sony/60 pl-1.5">
          <div className="mb-0.5 flex items-center justify-between">
            <span className="text-xxs font-bold uppercase tracking-wider text-sony">S1 · Sony · micro</span>
            <Sparkline seriesKey="cvd" width={64} height={12} stroke="auto" />
          </div>
          <Row label="SVS v3.0"><MetaValue meta={s1?.svs_score} render={(v) => fmtNum(v as number, 1)} /></Row>
          <Row label="CVD"><MetaValue meta={s1?.order_flow.cvd} render={(v) => fmtSigned(v as number, 0)} /></Row>
          <Row label="Absorption">
            <MetaValue meta={s1?.order_flow.absorption} render={(v) => (v ? 'OUI' : 'NON')} />
          </Row>
          <Row label="Aggressor"><MetaValue meta={s1?.order_flow.aggressor_ratio} render={(v) => fmtNum((v as number) * 100, 0) + ' %'} /></Row>
          <Row label="CHOP" alert={chopCrit}>
            <MetaValue meta={s1?.chop} render={(v) => fmtNum(v as number, 1)}
              className={chopCrit ? 'text-risk-red font-bold' : undefined} />
          </Row>
        </div>
        <div className="border-l-2 border-youssef/60 pl-1.5">
          <div className="mb-0.5 flex items-center justify-between">
            <span className="text-xxs font-bold uppercase tracking-wider text-youssef">S2 · Youssef · macro</span>
            <Sparkline seriesKey="eurusd" width={64} height={12} stroke="#facc15" />
          </div>
          <Row label="EUR/USD"><MetaValue meta={s2?.cascade.eurusd} render={(v) => fmtNum(v as number, 5)} /></Row>
          <Row label="VIX"><MetaValue meta={s2?.cascade.vix} render={(v) => fmtNum(v as number, 2)} /></Row>
          <Row label="Taux réels"><MetaValue meta={s2?.cascade.real_rates} render={(v) => fmtNum(v as number, 2) + ' %'} /></Row>
          <Row label="Score macro">
            {s2?.s2_macro_score.calibrated
              ? <span>{fmtNum(s2.s2_macro_score.value, 1)}</span>
              : <span className="font-bold text-risk-yellow" title="A3 — contribution live = 0 tant que non calibré">NON CALIBRÉ</span>}
          </Row>
        </div>
      </div>
    </Panel>
  )
}
