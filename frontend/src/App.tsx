/** Terminal Cholismo — layout 5 zones + barre statut + barre de touches (TASKS 3.2),
 *  organisé en ESPACES DE TRAVAIL nommés (lignée des terminaux financiers) : les colonnes du workspace actif
 *  réarrangent les panneaux du registre — chaque panneau reste traçable à un bloc du
 *  schéma. Fond teinté par le marqueur de session ; zones focusables A/B/C/D. */
import { useEffect } from 'react'
import { connectSSE } from '@/lib/sse'
import { KEY_HINTS, useKeyboardNav } from '@/lib/keyboard'
import { cn } from '@/lib/utils'
import { useTerminal, type ZoneKey } from '@/store/terminal'
import { useWorkspaces } from '@/store/workspace'
import { CommandBar } from '@/components/CommandBar'
import { PanelSlot } from '@/components/PanelSlot'
import { WorkspaceBar } from '@/components/WorkspaceBar'
import { Zone0StatusBar } from '@/panels/Zone0StatusBar'
import { SelfCheckDialog } from '@/panels/zoneC/SelfCheckDialog'
import { DecisionBlotter } from '@/panels/zoneD/DecisionBlotter'
import { JournalView } from '@/panels/views/JournalView'
import { LiveView } from '@/panels/views/LiveView'
import { OrchestratorConsole } from '@/panels/views/OrchestratorConsole'
import { ParamsView } from '@/panels/views/ParamsView'
import { PromptsView } from '@/panels/views/PromptsView'
import { RecapView } from '@/panels/views/RecapView'

const COLUMN_ZONES: ZoneKey[] = ['A', 'B', 'C']

function Zone({ zone, className, children }: {
  zone: ZoneKey; className?: string; children: React.ReactNode
}) {
  const focused = useTerminal((s) => s.focusZone === zone)
  return (
    <div className={cn('flex min-h-0 min-w-0 flex-col gap-1.5', focused && 'zone-focus', className)}
      role="region" aria-label={`Zone ${zone}`}>
      {children}
    </div>
  )
}

function FunctionKeyBar() {
  const view = useTerminal((s) => s.view)
  const wsName = useWorkspaces((s) => (s.workspaces.find((w) => w.id === s.activeId) ?? s.workspaces[0]).name)
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
      <span className="ml-auto uppercase text-term-faint">vue : {view} · espace : {wsName}</span>
    </footer>
  )
}

function WorkspaceGrid() {
  const workspace = useWorkspaces((s) => s.workspaces.find((w) => w.id === s.activeId) ?? s.workspaces[0])
  const editMode = useWorkspaces((s) => s.editMode)
  return (
    <>
      <main className="grid min-h-0 flex-1 grid-cols-[1fr_1.4fr_1.15fr] gap-1.5 p-1.5">
        {workspace.columns.map((column, index) => (
          <Zone key={COLUMN_ZONES[index]} zone={COLUMN_ZONES[index]}>
            {column.map((panelId) => <PanelSlot key={panelId} panelId={panelId} />)}
            {column.length === 0 && editMode && (
              <div className="grid flex-1 place-items-center border border-dashed border-term-border text-xxs text-term-faint">
                colonne vide — ◀ ▶ pour y déplacer un panneau
              </div>
            )}
          </Zone>
        ))}
      </main>
      {workspace.showBlotter && (
        <div className="h-44 shrink-0 px-1.5 pb-1.5">
          <Zone zone="D" className="h-full">
            <DecisionBlotter />
          </Zone>
        </div>
      )}
    </>
  )
}

export default function App() {
  useKeyboardNav()
  const marker = useTerminal((s) => s.session_identity?.session_marker ?? 'HORS_SESSION')
  const view = useTerminal((s) => s.view)

  useEffect(() => connectSSE(), [])

  return (
    <div className={cn('relative flex h-full flex-col', `session-${marker}`)}>
      <Zone0StatusBar />
      <CommandBar />
      <WorkspaceBar />

      {view === 'ORCHESTRATEUR' && <main className="min-h-0 flex-1"><OrchestratorConsole /></main>}
      {view === 'PROMPTS' && <main className="min-h-0 flex-1"><PromptsView /></main>}
      {view === 'JOURNAL' && <main className="flex min-h-0 flex-1 flex-col"><JournalView /></main>}
      {view === 'RECAP' && <main className="flex min-h-0 flex-1 flex-col"><RecapView /></main>}
      {view === 'LIVE' && <main className="flex min-h-0 flex-1 flex-col"><LiveView /></main>}
      {view === 'PARAMS' && <main className="flex min-h-0 flex-1 flex-col"><ParamsView /></main>}
      {view === 'TERMINAL' && <WorkspaceGrid />}

      <FunctionKeyBar />
      <SelfCheckDialog />
    </div>
  )
}
