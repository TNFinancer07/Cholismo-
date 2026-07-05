/** Emplacement de panneau dans un workspace : rend le composant du registre et, en mode
 *  édition, une poignée ◀ ▲ ▼ ▶ ✕ pour réarranger le layout (jamais les données). */
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, X } from 'lucide-react'
import { PANEL_REGISTRY } from '@/panels/registry'
import type { PanelId } from '@/store/workspace'
import { useWorkspaces } from '@/store/workspace'

export function PanelSlot({ panelId }: { panelId: PanelId }) {
  const editMode = useWorkspaces((s) => s.editMode)
  const def = PANEL_REGISTRY[panelId]
  const Component = def.component

  return (
    <div className="panel-slot relative flex min-h-0 flex-1 flex-col">
      {editMode && (
        <div className="flex h-4 shrink-0 items-center justify-between border border-b-0 border-router/50 bg-router/10 px-1">
          <span className="text-xxs font-bold uppercase text-router">{panelId} · {def.label}</span>
          <span className="flex items-center gap-0.5">
            {([['left', ChevronLeft], ['up', ChevronUp], ['down', ChevronDown], ['right', ChevronRight]] as const)
              .map(([direction, Icon]) => (
                <button key={direction} className="text-router/70 hover:text-router"
                  aria-label={`Déplacer ${panelId} ${direction}`}
                  onClick={() => useWorkspaces.getState().movePanel(panelId, direction)}>
                  <Icon size={11} />
                </button>
              ))}
            <button className="ml-1 text-router/70 hover:text-risk-red"
              aria-label={`Masquer ${panelId}`}
              onClick={() => useWorkspaces.getState().hidePanel(panelId)}>
              <X size={11} />
            </button>
          </span>
        </div>
      )}
      <Component />
    </div>
  )
}
