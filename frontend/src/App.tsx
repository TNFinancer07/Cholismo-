/** Terminal Cholismo — layout 5 zones + barre statut + barre de touches (TASKS 3.2).
 *  Le fond est teinté par le marqueur de session. Chaque zone est focusable au clavier
 *  (A/B/C/D) avec indicateur visuel. Les vues (V) : TERMINAL · ORCHESTRATEUR · PROMPTS. */
import { useEffect } from 'react'
import { connectSSE } from '@/lib/sse'
import { KEY_HINTS, useKeyboardNav } from '@/lib/keyboard'
import { cn } from '@/lib/utils'
import { useTerminal, type ZoneKey } from '@/store/terminal'
import { Zone0StatusBar } from '@/panels/Zone0StatusBar'
import { CascadePanel } from '@/panels/zoneA/CascadePanel'
import { MacroScorePanel } from '@/panels/zoneA/MacroScorePanel'
import { BridgewaterMatrix } from '@/panels/zoneA/BridgewaterMatrix'
import { S1S2Panel } from '@/panels/zoneB/S1S2Panel'
import { BridgePanel } from '@/panels/zoneB/BridgePanel'
import { SyncPanel } from '@/panels/zoneB/SyncPanel'
import { UnifiedSignalPanel } from '@/panels/zoneB/UnifiedSignalPanel'
import { Phase0DetailPanel } from '@/panels/zoneC/Phase0DetailPanel'
import { StreakPanel } from '@/panels/zoneC/StreakPanel'
import { CalibrationPanel } from '@/panels/zoneC/CalibrationPanel'
import { SelfCheckDialog } from '@/panels/zoneC/SelfCheckDialog'
import { DecisionBlotter } from '@/panels/zoneD/DecisionBlotter'
import { ScenarioPanel } from '@/panels/harness/ScenarioPanel'
import { ModePanel } from '@/panels/modes/ModePanel'
import { OrchestratorConsole } from '@/panels/views/OrchestratorConsole'
import { PromptsView } from '@/panels/views/PromptsView'

function Zone({ zone, className, children }: {
  zone: ZoneKey; className?: string; children: React.ReactNode
}) {
  const focused = useTerminal((s) => s.focusZone === zone)
  return (
    <div className={cn('flex min-h-0 flex-col gap-1.5', focused && 'zone-focus', className)}
      role="region" aria-label={`Zone ${zone}`}>
      {children}
    </div>
  )
}

function FunctionKeyBar() {
  const view = useTerminal((s) => s.view)
  return (
    <footer className="flex h-6 shrink-0 items-center gap-3 border-t border-term-border bg-term-panel px-2 text-xxs">
      {KEY_HINTS.map((hint) => (
        <span key={hint.key} className="text-term-dim">
          <kbd className="mr-1 rounded-sm border border-term-border bg-term-panel2 px-1 font-bold text-router">
            {hint.key}
          </kbd>
          {hint.label}
        </span>
      ))}
      <span className="ml-auto uppercase text-term-faint">vue : {view}</span>
    </footer>
  )
}

export default function App() {
  useKeyboardNav()
  const marker = useTerminal((s) => s.session_identity?.session_marker ?? 'HORS_SESSION')
  const view = useTerminal((s) => s.view)

  useEffect(() => connectSSE(), [])

  return (
    <div className={cn('flex h-full flex-col', `session-${marker}`)}>
      <Zone0StatusBar />

      {view === 'ORCHESTRATEUR' && <main className="min-h-0 flex-1"><OrchestratorConsole /></main>}
      {view === 'PROMPTS' && <main className="min-h-0 flex-1"><PromptsView /></main>}

      {view === 'TERMINAL' && (
        <main className="grid min-h-0 flex-1 grid-cols-[1fr_1.4fr_1.15fr] gap-1.5 p-1.5">
          {/* ZONE A — cascade macro (Youssef, canal lent) */}
          <Zone zone="A">
            <CascadePanel />
            <MacroScorePanel />
            <BridgewaterMatrix />
            <ScenarioPanel />
          </Zone>

          {/* ZONE B — le Router (or) */}
          <Zone zone="B">
            <UnifiedSignalPanel />
            <S1S2Panel />
            <div className="grid grid-cols-2 gap-1.5">
              <BridgePanel />
              <SyncPanel />
            </div>
          </Zone>

          {/* ZONE C — discipline / état cognitif */}
          <Zone zone="C">
            <Phase0DetailPanel />
            <StreakPanel />
            <CalibrationPanel />
            <ModePanel />
          </Zone>
        </main>
      )}

      {/* ZONE D — blotter event-sourced, pleine largeur */}
      {view === 'TERMINAL' && (
        <div className="h-44 shrink-0 px-1.5 pb-1.5">
          <Zone zone="D" className="h-full">
            <DecisionBlotter />
          </Zone>
        </div>
      )}

      <FunctionKeyBar />
      <SelfCheckDialog />
    </div>
  )
}
