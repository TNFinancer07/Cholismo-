/** Vues par mode (PRD §Vues par mode, post-MVP) — projection du mode courant :
 *  PRÉ-SESSION : briefing + schéma I/O JSON. LIVE : stack RMS 5 couches + chat contextuel
 *  (refuse si VIX>30 / CHOP≥61.8 ; arbres conditionnels PLACEHOLDER — MANIFEST).
 *  POST-SESSION : rapport JSON strict + statut audit Gemini (async, 20 trades). */
import { useMemo, useState } from 'react'
import { Layers, MessageSquareWarning, SendHorizonal } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'

const GLOSSARY: Record<string, string> = {
  CVD: 'Cumulative Volume Delta — pression nette acheteur/vendeur',
  GEX: 'Gamma Exposure — gamma net des dealers',
  CHOP: 'Choppiness Index — 61.8+ = marché sans direction',
  SVS: 'Sony Volatility Score v3.0 — lisibilité microstructure',
  RMS: 'Risk Management Stack — 5 couches de contrôle',
}

function PreSession() {
  const scenario = useTerminal((s) => s.scenario)
  const si = useTerminal((s) => s.session_identity)
  const briefing = useMemo(() => JSON.stringify({
    input: {
      session_marker: si?.session_marker, scenario: scenario?.current.name,
      checklist: ['phase0_rules', 'selfcheck_c5', 'calibration_c4'],
    },
    output: { decision_events: 'append-only', recon: 'ninjatrader_csv' },
  }, null, 2), [si?.session_marker, scenario?.current.name])
  return (
    <div className="space-y-1">
      <p className="text-xxs text-term-dim">
        Briefing : vérifier les règles Phase 0, remplir le self-check C5 (touche S), viser le
        process — pas le résultat. Sizing verrouillé 50 % tant que C4 n'est pas au vert.
      </p>
      <pre className="max-h-40 overflow-auto border border-term-grid bg-term-bg p-1 text-xxs text-term-dim">{briefing}</pre>
    </div>
  )
}

function LiveRmsStack() {
  const rms = useTerminal((s) => s.extras?.rms ?? null)
  const layers = ['L1 · taille max', 'L2 · stop obligatoire', 'L3 · perte/jour',
    'L4 · corrélation', 'L5 · kill-switch']
  const active = rms === null ? 0 : Math.min(5, Math.max(0, Math.ceil(rms)))
  return (
    <div>
      <div className="mb-0.5 flex items-center gap-1 text-xxs uppercase text-term-dim">
        <Layers size={10} aria-hidden /> Stack RMS 5 couches — niveau {rms === null ? '—' : fmtNum(rms, 1)}
      </div>
      <div className="space-y-0.5">
        {layers.map((label, i) => (
          <div key={label} className={cn('flex items-center justify-between border px-1.5 py-0.5 text-xxs',
            i < active ? 'border-risk-yellow/60 bg-risk-yellow/10 text-risk-yellow' : 'border-term-grid text-term-faint')}>
            {label}
            <span>{i < active ? 'ENGAGÉ' : 'repos'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function LiveChat() {
  const vix = useTerminal((s) => s.s2_state?.cascade.vix.value as number | null)
  const chop = useTerminal((s) => s.s1_state?.chop.value as number | null)
  const [log, setLog] = useState<{ q: string; a: string }[]>([])
  const [input, setInput] = useState('')
  const refusal = (vix !== null && vix > 30) ? `VIX ${fmtNum(vix, 1)} > 30 — entrée refusée.`
    : (chop !== null && chop >= 61.8) ? `CHOP ${fmtNum(chop, 1)} ≥ 61.8 — entrée refusée.` : null

  function ask() {
    if (!input.trim()) return
    const glossaryHit = Object.entries(GLOSSARY).find(([k]) => input.toUpperCase().includes(k))
    const answer = refusal ?? (glossaryHit
      ? `${glossaryHit[0]} : ${glossaryHit[1]}`
      : 'PLACEHOLDER — arbre conditionnel non AUTORITÉ (reference/MANIFEST.md) ; seule la règle de refus VIX/CHOP est canonique.')
    setLog((l) => [...l.slice(-3), { q: input, a: answer }])
    setInput('')
  }

  return (
    <div className="mt-1.5 border-t border-term-grid pt-1">
      <div className="mb-0.5 flex items-center gap-1 text-xxs uppercase text-term-dim">
        <MessageSquareWarning size={10} aria-hidden /> Chat contextuel
        {refusal && <Badge variant="red">refus actif</Badge>}
      </div>
      <div className="max-h-24 space-y-0.5 overflow-auto text-xxs">
        {log.map((entry, i) => (
          <div key={i}>
            <div className="text-term-dim">&gt; {entry.q}</div>
            <div className={cn(entry.a.includes('refusée') ? 'text-risk-red' : 'text-term-text')}>{entry.a}</div>
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1">
        <input value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') ask() }}
          placeholder="question marché… (glossaire : CVD, GEX, CHOP, SVS, RMS)"
          className="h-6 flex-1 border border-term-border bg-term-bg px-1.5 text-xxs outline-none focus:border-router" />
        <button onClick={ask} className="border border-term-border px-1.5 text-term-dim hover:text-term-text"
          aria-label="Envoyer"><SendHorizonal size={11} /></button>
      </div>
    </div>
  )
}

function PostSession() {
  const decisions = useTerminal((s) => s.decisions)
  const cal = useTerminal((s) => s.calibration)
  const report = useMemo(() => JSON.stringify({
    report_version: '1.0',
    decisions: decisions.length,
    go: decisions.filter((d) => d.decision === 'GO').length,
    no_go: decisions.filter((d) => d.decision === 'NO_GO').length,
    timeouts: decisions.filter((d) => d.reason === 'timeout').length,
    reconciled: decisions.filter((d) => d.recon?.matched).length,
    sharpe: cal?.sharpe.displayable ? cal.sharpe.sharpe : null,
    gemini_audit: { cadence: 'tous les 20 trades', mode: 'async',
      status: (cal?.quantitative.n_trades ?? 0) >= 20 ? 'ELIGIBLE' : 'EN ATTENTE (<20 trades)' },
  }, null, 2), [decisions, cal])
  return (
    <pre className="max-h-48 overflow-auto border border-term-grid bg-term-bg p-1 text-xxs text-term-dim">{report}</pre>
  )
}

export function ModePanel() {
  const mode = useTerminal((s) => s.session_identity?.operational_mode ?? 'PRE_SESSION')
  const title = mode === 'PRE_SESSION' ? 'Vue pré-session' : mode === 'LIVE' ? 'Mode Live' : 'Vue post-session'
  return (
    <Panel code="MODE" title={title} block="session_identity.operational_mode">
      {mode === 'PRE_SESSION' && <PreSession />}
      {mode === 'LIVE' && (<><LiveRmsStack /><LiveChat /></>)}
      {mode === 'POST_SESSION' && <PostSession />}
    </Panel>
  )
}
