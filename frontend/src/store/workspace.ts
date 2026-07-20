/** Espaces de travail (lignée des terminaux financiers) — multi-layouts nommés, personnalisables,
 *  persistés par opérateur. Un workspace ne fait que RÉARRANGER les panneaux existants
 *  (chacun traçable à un bloc du schéma, CLAUDE §1) : il ne crée aucune donnée, ne
 *  contourne aucun verrou. Pure projection d'affichage, volatile en localStorage. */
import { create } from 'zustand'
import { useTerminal } from './terminal'

/** Identifiants canoniques des panneaux disponibles (couverts par panels/registry). */
export const PANEL_IDS = ['A1', 'A2', 'A3', 'EC', 'S2P', 'MOCK', 'B1', 'B2', 'B3', 'B4',
  'S1S', 'OB', 'TP', 'CVD', 'HM', 'FP', 'CDS', 'IA', 'C1', 'C2', 'C4', 'MODE'] as const
export type PanelId = (typeof PANEL_IDS)[number]

export interface Workspace {
  id: string
  name: string
  builtin: boolean
  columns: [PanelId[], PanelId[], PanelId[]]
  showBlotter: boolean
}

function builtins(): Workspace[] {
  return [
    { id: 'defaut', name: 'DÉFAUT', builtin: true, showBlotter: true,
      columns: [['A1', 'S2P', 'A3', 'MOCK'], ['B4', 'S1S', 'B1'], ['EC', 'C1', 'C2', 'C4', 'MODE']] },
    { id: 'micro', name: 'MICRO · S1', builtin: true, showBlotter: true,
      columns: [['S1S', 'B2', 'IA', 'FP'], ['B4', 'OB', 'CVD', 'HM', 'CDS', 'B1'], ['TP', 'EC', 'B3', 'C1', 'C2', 'MOCK']] },
    { id: 'macro', name: 'MACRO · S2', builtin: true, showBlotter: false,
      columns: [['A1', 'A3', 'EC'], ['S2P', 'A2'], ['B4', 'B3', 'MOCK']] },
    { id: 'discipline', name: 'DISCIPLINE', builtin: true, showBlotter: true,
      columns: [['C1', 'C2'], ['B4', 'C4'], ['MODE', 'MOCK']] },
  ]
}

// v9 : ajout du panneau CDS (CVD stratifié par taille, D-038) à l'espace MICRO — bump de clé :
// les layouts persistés antérieurs repartent des intégrés (les PERSO se recréent ; pas de
// migration silencieuse d'un panneau invisible).
const STORAGE_KEY = () => `cholismo.workspaces.${useTerminal.getState().operator}.v9`

interface Persisted { workspaces: Workspace[]; activeId: string }

function sanitize(ws: Workspace): Workspace {
  const seen = new Set<string>()
  const columns = ws.columns.map((col) =>
    col.filter((id) => {
      const ok = (PANEL_IDS as readonly string[]).includes(id) && !seen.has(id)
      if (ok) seen.add(id)
      return ok
    })) as Workspace['columns']
  while (columns.length < 3) columns.push([])
  return { ...ws, columns: columns.slice(0, 3) as Workspace['columns'] }
}

function load(): Persisted {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY())
    if (raw) {
      const parsed = JSON.parse(raw) as Persisted
      if (Array.isArray(parsed.workspaces) && parsed.workspaces.length > 0) {
        const workspaces = parsed.workspaces.map(sanitize)
        const activeId = workspaces.some((w) => w.id === parsed.activeId)
          ? parsed.activeId : workspaces[0].id
        return { workspaces, activeId }
      }
    }
  } catch { /* stockage corrompu -> repartir des intégrés */ }
  return { workspaces: builtins(), activeId: 'defaut' }
}

interface WorkspaceStore {
  workspaces: Workspace[]
  activeId: string
  editMode: boolean

  active: () => Workspace
  setActive: (id: string) => void
  setEditMode: (on: boolean) => void
  movePanel: (panelId: PanelId, direction: 'left' | 'right' | 'up' | 'down') => void
  hidePanel: (panelId: PanelId) => void
  showPanel: (panelId: PanelId, column?: number) => void
  toggleBlotter: () => void
  duplicateActive: () => void
  renameActive: (name: string) => void
  deleteActive: () => void
  resetBuiltins: () => void
}

export const useWorkspaces = create<WorkspaceStore>((set, get) => {
  const initial = load()

  function persistAnd(update: Partial<Pick<WorkspaceStore, 'workspaces' | 'activeId' | 'editMode'>>) {
    set(update as never)
    const { workspaces, activeId } = get()
    try {
      window.localStorage.setItem(STORAGE_KEY(), JSON.stringify({ workspaces, activeId }))
    } catch { /* quota/privé : le workspace reste utilisable, juste non persisté */ }
  }

  function updateActive(mutate: (ws: Workspace) => Workspace) {
    const { workspaces, activeId } = get()
    persistAnd({ workspaces: workspaces.map((w) => (w.id === activeId ? sanitize(mutate(w)) : w)) })
  }

  return {
    ...initial,
    editMode: false,

    active: () => {
      const { workspaces, activeId } = get()
      return workspaces.find((w) => w.id === activeId) ?? workspaces[0]
    },

    setActive: (id) => {
      if (get().workspaces.some((w) => w.id === id)) persistAnd({ activeId: id })
    },

    setEditMode: (on) => set({ editMode: on }),

    movePanel: (panelId, direction) => updateActive((ws) => {
      const columns = ws.columns.map((c) => [...c]) as Workspace['columns']
      const colIndex = columns.findIndex((c) => c.includes(panelId))
      if (colIndex < 0) return ws
      const row = columns[colIndex].indexOf(panelId)
      if (direction === 'up' && row > 0) {
        [columns[colIndex][row - 1], columns[colIndex][row]] =
          [columns[colIndex][row], columns[colIndex][row - 1]]
      } else if (direction === 'down' && row < columns[colIndex].length - 1) {
        [columns[colIndex][row + 1], columns[colIndex][row]] =
          [columns[colIndex][row], columns[colIndex][row + 1]]
      } else if (direction === 'left' && colIndex > 0) {
        columns[colIndex].splice(row, 1)
        columns[colIndex - 1].push(panelId)
      } else if (direction === 'right' && colIndex < 2) {
        columns[colIndex].splice(row, 1)
        columns[colIndex + 1].push(panelId)
      }
      return { ...ws, columns }
    }),

    hidePanel: (panelId) => updateActive((ws) => ({
      ...ws,
      columns: ws.columns.map((c) => c.filter((id) => id !== panelId)) as Workspace['columns'],
    })),

    showPanel: (panelId, column = 0) => updateActive((ws) => {
      if (ws.columns.some((c) => c.includes(panelId))) return ws
      const columns = ws.columns.map((c) => [...c]) as Workspace['columns']
      columns[Math.min(2, Math.max(0, column))].push(panelId)
      return { ...ws, columns }
    }),

    toggleBlotter: () => updateActive((ws) => ({ ...ws, showBlotter: !ws.showBlotter })),

    duplicateActive: () => {
      const { workspaces } = get()
      const source = get().active()
      const customCount = workspaces.filter((w) => !w.builtin).length
      const copy: Workspace = {
        ...source,
        id: `perso-${Date.now().toString(36)}`,
        name: `PERSO ${customCount + 1}`,
        builtin: false,
        columns: source.columns.map((c) => [...c]) as Workspace['columns'],
      }
      persistAnd({ workspaces: [...workspaces, copy], activeId: copy.id })
      set({ editMode: true })
    },

    renameActive: (name) => {
      const trimmed = name.trim().toUpperCase().slice(0, 18)
      if (!trimmed) return
      updateActive((ws) => (ws.builtin ? ws : { ...ws, name: trimmed }))
    },

    deleteActive: () => {
      const { workspaces, activeId } = get()
      const target = workspaces.find((w) => w.id === activeId)
      if (!target || target.builtin) return  // les intégrés ne se suppriment pas
      const remaining = workspaces.filter((w) => w.id !== activeId)
      persistAnd({ workspaces: remaining, activeId: remaining[0].id })
    },

    resetBuiltins: () => {
      const customs = get().workspaces.filter((w) => !w.builtin)
      persistAnd({ workspaces: [...builtins(), ...customs], activeId: 'defaut' })
    },
  }
})

/** Panneaux du workspace actif non affichés (pour le plateau « ajouter » du mode édition). */
export function hiddenPanels(ws: Workspace): PanelId[] {
  const visible = new Set(ws.columns.flat())
  return PANEL_IDS.filter((id) => !visible.has(id))
}
