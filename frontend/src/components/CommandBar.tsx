/** Barre de commande — la signature du Bloomberg Terminal : `/` ouvre la ligne, on tape
 *  un mnémonique, Entrée = <GO>. Pure NAVIGATION/reflet : les commandes GO/NOGO passent
 *  par les mêmes verrous serveur que les boutons (Phase 0, C5, fenêtre C3) — la barre
 *  n'ouvre aucun chemin privilégié. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { api } from '@/lib/api'
import { refreshScenario, refreshSelfcheck } from '@/lib/sse'
import { cn } from '@/lib/utils'
import { useTerminal, type ViewKey, type ZoneKey } from '@/store/terminal'

interface Command {
  mnemonic: string
  aliases?: string[]
  label: string
  run: () => Promise<string> | string
}

function useCommands(): Command[] {
  return useMemo(() => {
    const store = () => useTerminal.getState()
    const focus = (zone: ZoneKey, label: string): Command => ({
      mnemonic: zone, label, run: () => { store().set({ focusZone: zone, view: 'TERMINAL' }); return `focus zone ${zone}` },
    })
    const panel = (code: string, zone: ZoneKey): Command => ({
      mnemonic: code, label: `panneau ${code} (zone ${zone})`,
      run: () => { store().set({ focusZone: zone, view: 'TERMINAL' }); return `focus ${code}` },
    })
    const mode = (mnemonic: string, value: string, aliases: string[] = []): Command => ({
      mnemonic, aliases, label: `mode ${value}`,
      run: async () => { await api.setMode(value); return `mode → ${value}` },
    })
    const view = (mnemonic: string, value: ViewKey, aliases: string[] = []): Command => ({
      mnemonic, aliases, label: `vue ${value}`,
      run: () => { store().set({ view: value }); return `vue → ${value}` },
    })
    const scenario = (mnemonic: string, name: string, aliases: string[] = []): Command => ({
      mnemonic, aliases, label: `scénario ${name}`,
      run: async () => { await api.setScenario({ name }); await refreshScenario(); return `scénario → ${name}` },
    })
    return [
      focus('A', 'zone A — cascade macro'), focus('B', 'zone B — Router'),
      focus('C', 'zone C — discipline'), focus('D', 'zone D — decision log'),
      panel('A1', 'A'), panel('A2', 'A'), panel('A3', 'A'),
      panel('B1', 'B'), panel('B2', 'B'), panel('B3', 'B'), panel('B4', 'B'),
      panel('C1', 'C'), panel('C2', 'C'), panel('C4', 'C'),
      mode('LIVE', 'LIVE'), mode('PRE', 'PRE_SESSION', ['PRESESSION']),
      mode('POST', 'POST_SESSION', ['POSTSESSION']),
      view('TERM', 'TERMINAL', ['TERMINAL']), view('ORCH', 'ORCHESTRATEUR', ['ORCHESTRATEUR']),
      view('PROMPTS', 'PROMPTS'),
      scenario('CALME', 'calme'), scenario('NEWS', 'news_eur_tier1', ['EUR']),
      scenario('STREAK', 'streak_loss'), scenario('VIX', 'vix_spike', ['SPIKE']),
      scenario('CUSTOM', 'custom'),
      {
        mnemonic: 'GO', label: 'décision GO (mêmes verrous serveur : Phase 0, C5, C3)',
        run: async () => { await api.postDecision(store().operator, 'GO'); return 'DecisionEvent GO écrit' },
      },
      {
        mnemonic: 'NOGO', aliases: ['NO-GO', 'NO_GO'], label: 'décision NO-GO',
        run: async () => { await api.postDecision(store().operator, 'NO_GO'); return 'DecisionEvent NO_GO écrit' },
      },
      {
        mnemonic: 'SC', aliases: ['SELFCHECK', 'C5'], label: 'ouvrir le self-check C5',
        run: () => { store().set({ selfcheckOpen: true }); void refreshSelfcheck(); return 'self-check ouvert' },
      },
      {
        mnemonic: 'HELP', aliases: ['?'], label: 'liste des mnémoniques',
        run: () => 'A·B·C·D / A1…C4 focus · LIVE/PRE/POST mode · TERM/ORCH/PROMPTS vue · CALME/NEWS/STREAK/VIX/CUSTOM scénario · GO/NOGO · SC',
      },
    ]
  }, [])
}

export function CommandBar() {
  const open = useTerminal((s) => s.commandOpen)
  const [input, setInput] = useState('')
  const [feedback, setFeedback] = useState<{ text: string; error: boolean } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const commands = useCommands()

  useEffect(() => {
    if (open) {
      setInput(''); setFeedback(null)
      window.setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  if (!open) return null

  const query = input.trim().toUpperCase()
  const matches = query
    ? commands.filter((c) => c.mnemonic.startsWith(query)
        || c.aliases?.some((a) => a.startsWith(query)))
    : commands.slice(0, 8)

  async function execute() {
    const exact = commands.find((c) => c.mnemonic === query || c.aliases?.includes(query))
    const target = exact ?? (matches.length === 1 ? matches[0] : null)
    if (!target) {
      setFeedback({ text: `mnémonique inconnu : ${query || '∅'} — HELP pour la liste`, error: true })
      return
    }
    try {
      const result = await target.run()
      setFeedback({ text: result, error: false })
      window.setTimeout(() => useTerminal.getState().set({ commandOpen: false }), 650)
    } catch (err) {
      setFeedback({ text: (err as Error).message, error: true })
    }
  }

  return (
    <div className="absolute inset-x-0 top-9 z-40 border-b-2 border-router bg-term-panel shadow-2xl"
      role="combobox" aria-expanded aria-label="Barre de commande">
      <div className="flex h-8 items-center gap-2 px-2">
        <ChevronRight size={14} className="text-router" aria-hidden />
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => { setInput(e.target.value); setFeedback(null) }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void execute()
            if (e.key === 'Escape') useTerminal.getState().set({ commandOpen: false })
            if (e.key === 'Tab') { e.preventDefault(); if (matches[0]) setInput(matches[0].mnemonic) }
          }}
          placeholder="mnémonique… (HELP pour la liste)"
          className="h-6 flex-1 border-0 bg-transparent font-mono text-sm uppercase tracking-widest text-router placeholder:normal-case placeholder:tracking-normal placeholder:text-term-faint focus:outline-none"
          spellCheck={false}
        />
        <span className="rounded-sm border border-router px-1.5 py-0.5 text-xxs font-black text-router">
          ⏎ &lt;GO&gt;
        </span>
      </div>
      {feedback && (
        <div className={cn('border-t border-term-border px-7 py-0.5 text-xxs',
          feedback.error ? 'text-risk-red' : 'text-risk-green')}>
          {feedback.text}
        </div>
      )}
      {!feedback && matches.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-0.5 border-t border-term-border px-7 py-1 text-xxs">
          {matches.slice(0, 8).map((c) => (
            <button key={c.mnemonic} className="text-term-dim hover:text-term-text"
              onClick={() => { setInput(c.mnemonic); inputRef.current?.focus() }}>
              <span className="font-bold text-router">{c.mnemonic}</span> {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
