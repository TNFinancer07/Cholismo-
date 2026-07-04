/** Harnais de démo — la couture du mock (CLAUDE §4) : scénarios, sliders
 *  VIX/CHOP/CVD/GEX/RMS, coupure de sources (pour VÉRIFIER que STALE/ABSENT s'affichent).
 *  Ce panneau pilote le MockDataSource, jamais le moteur de décision. */
import { useState } from 'react'
import { Power, PowerOff } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { api } from '@/lib/api'
import { refreshScenario } from '@/lib/sse'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'

const SLIDER_SPEC: Record<string, { min: number; max: number; step: number }> = {
  vix: { min: 9, max: 45, step: 0.5 },
  chop: { min: 0, max: 100, step: 0.5 },
  cvd: { min: -2500, max: 2500, step: 50 },
  gex: { min: -2e9, max: 4e9, step: 1e8 },
  rms: { min: 0, max: 5, step: 0.1 },
}

export function ScenarioPanel() {
  const scenario = useTerminal((s) => s.scenario)
  const sources = useTerminal((s) => s.sources)
  const [sliders, setSliders] = useState<Record<string, number>>({})

  async function apply(name: string, withSliders = false) {
    await api.setScenario({ name, sliders: withSliders ? sliders : undefined })
      .catch(() => undefined)
    await refreshScenario()
  }

  return (
    <Panel code="MOCK" title="Scénarios & pathologies" block="MarketDataSource (couture)">
      <div className="flex flex-wrap gap-1">
        {scenario?.available.map((s) => (
          <button key={s.name}
            className={cn('border px-1.5 py-0.5 text-xxs uppercase',
              scenario.current.name === s.name
                ? 'border-router text-router'
                : 'border-term-border text-term-dim hover:text-term-text')}
            onClick={() => void apply(s.name)}>
            {s.label}
          </button>
        ))}
      </div>

      {scenario?.current.name === 'custom' && (
        <div className="mt-1.5 space-y-1 border-t border-term-grid pt-1">
          {Object.entries(SLIDER_SPEC).map(([key, spec]) => (
            <label key={key} className="flex items-center gap-2 text-xxs">
              <span className="w-8 uppercase text-term-dim">{key}</span>
              <input type="range" min={spec.min} max={spec.max} step={spec.step}
                className="h-1 flex-1 accent-[#f0b429]"
                value={sliders[key] ?? scenario.current.base[key] ?? 0}
                onChange={(e) => setSliders((s) => ({ ...s, [key]: Number(e.target.value) }))}
                onMouseUp={() => void apply('custom', true)}
                onTouchEnd={() => void apply('custom', true)} />
              <span className="w-14 text-right tabular-nums">
                {key === 'gex'
                  ? ((sliders[key] ?? scenario.current.base[key] ?? 0) / 1e9).toFixed(1) + 'G'
                  : (sliders[key] ?? scenario.current.base[key] ?? 0).toFixed(1)}
              </span>
            </label>
          ))}
        </div>
      )}

      <div className="mt-1.5 border-t border-term-grid pt-1">
        <div className="mb-0.5 text-xxs uppercase text-term-faint">
          sources amont — couper pour vérifier STALE → ABSENT (TASKS 2.4)
        </div>
        <div className="flex flex-wrap gap-1">
          {sources && Object.entries(sources).map(([name, info]) => (
            <button key={name}
              className={cn('inline-flex items-center gap-1 border px-1.5 py-0.5 text-xxs',
                info.up ? 'border-risk-green/50 text-risk-green' : 'border-risk-red text-risk-red')}
              title={`champs : ${info.fields.join(', ')}`}
              onClick={async () => {
                await api.toggleSource(name, !info.up).catch(() => undefined)
                await refreshScenario()
              }}>
              {info.up ? <Power size={9} aria-hidden /> : <PowerOff size={9} aria-hidden />}
              {name}
            </button>
          ))}
        </div>
      </div>
    </Panel>
  )
}
