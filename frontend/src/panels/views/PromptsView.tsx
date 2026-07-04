/** Onglet « Prompts & Contextes » (Étape 9) — 6 blocs copiables. AUCUN artifact
 *  /reference/ n'existe dans ce dépôt : chaque bloc est explicitement PLACEHOLDER
 *  (reference/MANIFEST.md) sauf le ContextSchema injecté, qui est le schéma réel. */
import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { useTerminal } from '@/store/terminal'

function block(title: string, body: string, authority: boolean) {
  return { title, body, authority }
}

export function PromptsView() {
  const [copied, setCopied] = useState<number | null>(null)
  const schema = useTerminal((s) => ({
    session_identity: s.session_identity, s1_state: s.s1_state, s2_state: s.s2_state,
    bridge_variables: s.bridge_variables, sync_state: s.sync_state,
    unified_signal_output: s.unified_signal_output,
  }))

  const blocks = [
    block('Contexte système', 'PLACEHOLDER — à extraire des blocs AUTORITÉ de /reference/ quand ils existeront (MANIFEST.md). Ne rien inventer.', false),
    block('Phase A — pré-session', 'PLACEHOLDER — brief opérateur : règles Phase 0, self-check C5, sizing 50 %.', false),
    block('Phase B — live', 'PLACEHOLDER — lecture marché ; seule règle canonique : refus si VIX > 30 ou CHOP ≥ 61.8.', false),
    block('Phase C — post-session', 'PLACEHOLDER — journal, erreurs A/B/C, réconciliation NinjaTrader.', false),
    block('Audit Gemini (20 trades)', 'PLACEHOLDER — audit async tous les 20 trades ; jamais dans le hot path (CLAUDE §7).', false),
    block('ContextSchema injecté (réel, live)', JSON.stringify(schema, null, 2), true),
  ]

  return (
    <div className="grid h-full grid-cols-3 gap-1.5 overflow-auto p-1.5">
      {blocks.map((b, i) => (
        <Panel key={b.title} code={`P${i + 1}`} title={b.title}
          block={b.authority ? 'AUTORITÉ' : 'PLACEHOLDER'}
          right={
            <div className="flex items-center gap-1">
              <Badge variant={b.authority ? 'green' : 'yellow'}>
                {b.authority ? 'AUTORITÉ' : 'PLACEHOLDER'}
              </Badge>
              <button className="text-term-dim hover:text-term-text" aria-label={`Copier ${b.title}`}
                onClick={async () => {
                  await navigator.clipboard.writeText(b.body).catch(() => undefined)
                  setCopied(i); setTimeout(() => setCopied(null), 1200)
                }}>
                {copied === i ? <Check size={11} className="text-risk-green" /> : <Copy size={11} />}
              </button>
            </div>
          }>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xxs text-term-dim">{b.body}</pre>
        </Panel>
      ))}
    </div>
  )
}
