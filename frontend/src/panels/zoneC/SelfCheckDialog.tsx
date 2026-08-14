/** C5 — Self-check cognitif OBLIGATOIRE : bloque le GO tant que non renseigné (vérifié
 *  serveur, HTTP 412). Quatre booléens explicites ; validité 60 min (TTL Redis). */
import { useState } from 'react'
import { BrainCircuit, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { refreshSelfcheck } from '@/lib/sse'
import { useTerminal } from '@/store/terminal'
import { cn } from '@/lib/utils'

const QUESTIONS: { key: string; label: string }[] = [
  { key: 'sleep_ok', label: 'Sommeil suffisant (≥ 7 h)' },
  { key: 'focus_ok', label: 'Focus disponible — pas de distraction majeure' },
  { key: 'no_tilt', label: 'Pas de tilt / revenge trading' },
  { key: 'plan_written', label: 'Plan de session écrit et relu' },
]

export function SelfCheckDialog() {
  const open = useTerminal((s) => s.selfcheckOpen)
  const operator = useTerminal((s) => s.operator)
  const present = useTerminal((s) => s.selfcheckPresent)
  const [answers, setAnswers] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null
  const allAnswered = QUESTIONS.every((q) => answers[q.key] !== undefined)

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70" role="dialog" aria-modal
      aria-label="Self-check cognitif C5">
      <div className="w-[28rem] border border-term-border bg-term-panel shadow-2xl">
        <header className="flex items-center justify-between border-b border-term-border bg-term-panel2 px-2 py-1">
          <span className="inline-flex items-center gap-1.5 text-xxs font-bold uppercase tracking-wider">
            <BrainCircuit size={12} className="text-router" aria-hidden />
            C5 · Self-check cognitif — {operator}
          </span>
          <button onClick={() => useTerminal.getState().set({ selfcheckOpen: false })}
            className="text-term-dim hover:text-term-text" aria-label="Fermer"><X size={14} /></button>
        </header>
        <div className="space-y-1 p-2">
          {present && (
            <p className="border border-risk-green/40 bg-risk-green/10 px-1.5 py-0.5 text-xxs text-risk-green">
              Self-check déjà valide pour cette fenêtre — re-remplir le remplace.
            </p>
          )}
          {QUESTIONS.map((q) => (
            <div key={q.key} className="flex items-center justify-between gap-2 border-b border-term-grid py-1">
              <span className="text-xs">{q.label}</span>
              <div className="flex gap-1">
                {[true, false].map((v) => (
                  <button key={String(v)}
                    className={cn('border px-2 py-0.5 text-xxs font-bold uppercase',
                      answers[q.key] === v
                        ? v ? 'border-risk-green bg-risk-green/20 text-risk-green'
                            : 'border-risk-red bg-risk-red/20 text-risk-red'
                        : 'border-term-border text-term-dim hover:text-term-text')}
                    onClick={() => setAnswers((a) => ({ ...a, [q.key]: v }))}>
                    {v ? 'OUI' : 'NON'}
                  </button>
                ))}
              </div>
            </div>
          ))}
          {error && <p className="text-xxs text-risk-red">{error}</p>}
          <Button className="w-full" size="lg" variant="router" disabled={!allAnswered || busy}
            onClick={async () => {
              setBusy(true); setError(null)
              try {
                await api.postSelfcheck(operator, answers)
                await refreshSelfcheck()
                useTerminal.getState().set({ selfcheckOpen: false })
              } catch (err) {
                setError((err as Error).message)
              } finally { setBusy(false) }
            }}>
            Enregistrer le self-check
          </Button>
          <p className="text-center text-xxs text-term-faint">
            un GO sans self-check est refusé par le serveur (HTTP 412) — le verrou n'est pas dans l'UI
          </p>
        </div>
      </div>
    </div>
  )
}
