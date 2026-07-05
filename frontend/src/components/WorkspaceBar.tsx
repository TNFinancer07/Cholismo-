/** Barre d'espaces de travail (lignée Eikon) — onglets nommés sous la barre de statut,
 *  duplication, mode édition (renommer, masquer/déplacer les panneaux, blotter on/off).
 *  Touches 1-9 = bascule directe ; mnémoniques (DEFAUT, MICRO…) dans la barre de commande. */
import { useState } from 'react'
import { Copy, Pencil, PencilOff, Plus, Table2, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { hiddenPanels, useWorkspaces } from '@/store/workspace'
import { PANEL_REGISTRY } from '@/panels/registry'

export function WorkspaceBar() {
  const workspaces = useWorkspaces((s) => s.workspaces)
  const activeId = useWorkspaces((s) => s.activeId)
  const editMode = useWorkspaces((s) => s.editMode)
  const store = useWorkspaces
  const active = workspaces.find((w) => w.id === activeId) ?? workspaces[0]
  const [renaming, setRenaming] = useState('')

  return (
    <div className="flex h-6 shrink-0 items-center gap-1 border-b border-term-border bg-term-panel2 px-2"
      role="tablist" aria-label="Espaces de travail">
      <span className="mr-1 text-xxs uppercase tracking-wider text-term-faint">Espaces</span>

      {workspaces.map((ws, index) => (
        <button key={ws.id} role="tab" aria-selected={ws.id === activeId}
          className={cn('flex h-full items-center gap-1 border-b-2 px-2 text-xxs font-semibold uppercase tracking-wide',
            ws.id === activeId
              ? 'border-router text-router'
              : 'border-transparent text-term-dim hover:text-term-text')}
          title={`${ws.name} — touche ${index + 1}`}
          onClick={() => store.getState().setActive(ws.id)}>
          <span className="text-term-faint">{index + 1}</span>
          {ws.name}
          {!ws.builtin && <span className="text-term-faint" title="espace personnalisé">◆</span>}
        </button>
      ))}

      <button className="ml-1 text-term-dim hover:text-router" title="Dupliquer l'espace actif"
        aria-label="Dupliquer l'espace actif"
        onClick={() => store.getState().duplicateActive()}>
        <Copy size={11} />
      </button>
      <button className={cn('text-term-dim hover:text-router', editMode && 'text-router')}
        title={editMode ? 'Quitter le mode édition' : 'Personnaliser l\'espace (déplacer/masquer les panneaux)'}
        aria-label="Mode édition"
        onClick={() => store.getState().setEditMode(!editMode)}>
        {editMode ? <PencilOff size={11} /> : <Pencil size={11} />}
      </button>

      {editMode && (
        <div className="ml-2 flex min-w-0 flex-1 items-center gap-2 overflow-x-auto">
          {!active.builtin && (
            <>
              <input
                defaultValue={active.name}
                onChange={(e) => setRenaming(e.target.value)}
                onBlur={() => renaming && store.getState().renameActive(renaming)}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                className="h-4 w-24 border border-term-border bg-term-bg px-1 text-xxs uppercase text-term-text focus:border-router focus:outline-none"
                aria-label="Renommer l'espace"
              />
              <button className="text-term-dim hover:text-risk-red" title="Supprimer cet espace personnalisé"
                aria-label="Supprimer l'espace"
                onClick={() => store.getState().deleteActive()}>
                <Trash2 size={11} />
              </button>
            </>
          )}
          <button
            className={cn('inline-flex items-center gap-1 border px-1.5 text-xxs uppercase',
              active.showBlotter ? 'border-router/60 text-router' : 'border-term-border text-term-dim')}
            title="Afficher/masquer le Decision Log (zone D)"
            onClick={() => store.getState().toggleBlotter()}>
            <Table2 size={10} aria-hidden /> blotter
          </button>
          {hiddenPanels(active).length > 0 && (
            <span className="flex items-center gap-1">
              <span className="text-xxs text-term-faint">masqués :</span>
              {hiddenPanels(active).map((id) => (
                <button key={id}
                  className="inline-flex items-center gap-0.5 border border-term-border px-1 text-xxs text-term-dim hover:border-router hover:text-router"
                  title={`Ajouter ${PANEL_REGISTRY[id].label} (colonne 1, puis ◀▶ pour déplacer)`}
                  onClick={() => store.getState().showPanel(id, 0)}>
                  <Plus size={9} aria-hidden />{id}
                </button>
              ))}
            </span>
          )}
          <span className="whitespace-nowrap text-xxs text-term-faint">
            ◀ ▲ ▼ ▶ déplacent · ✕ masque — layout persisté (localStorage, par opérateur)
          </span>
        </div>
      )}
    </div>
  )
}
