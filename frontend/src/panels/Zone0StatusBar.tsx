/** ZONE 0 — barre de statut (`session_identity`). Horloge double Montréal+CET, marqueur de
 *  session (teinte le fond via App), 3 modes, PHASE 0 GÉANT (reflet du moteur déterministe,
 *  jamais overridable ici), glyphe état maître, badge opérateur. */
import { Lock, LockOpen, Radio, RadioTower, ShieldAlert, ShieldCheck, ShieldHalf } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { fmtClock } from '@/lib/format'
import { cn } from '@/lib/utils'
import { effectivePhase0, MODES, useTerminal } from '@/store/terminal'

const MODE_LABELS: Record<string, string> = {
  PRE_SESSION: 'PRÉ-SESSION', LIVE: 'LIVE', POST_SESSION: 'POST-SESSION',
}
const MARKER_LABELS: Record<string, string> = {
  LONDRES_OBS: 'LONDRES OBS', OVERLAP_NY: 'OVERLAP NY', HORS_SESSION: 'HORS SESSION',
}

function MasterGlyph() {
  const master = useTerminal((s) => s.session_identity?.master_state)
  if (master === 'READY') {
    return <span className="inline-flex items-center gap-1 text-risk-green"><ShieldCheck size={14} aria-hidden />READY</span>
  }
  if (master === 'DEGRADED') {
    return <span className="inline-flex items-center gap-1 text-risk-yellow"><ShieldHalf size={14} aria-hidden />DEGRADED</span>
  }
  return <span className="inline-flex items-center gap-1 text-risk-red"><ShieldAlert size={14} aria-hidden />NOT READY</span>
}

function Clocks() {
  const nowTick = useTerminal((s) => s.nowTick)
  const date = new Date(nowTick * 1000)
  return (
    <div className="flex items-baseline gap-2 tabular-nums">
      <span title="America/Montreal">MTL <b className="text-term-text">{fmtClock(date, 'America/Montreal')}</b></span>
      <span title="Europe/Paris (CET)" className="text-term-dim">CET <b className="text-term-text">{fmtClock(date, 'Europe/Paris')}</b></span>
    </div>
  )
}

export function Zone0StatusBar() {
  const si = useTerminal((s) => s.session_identity)
  const operator = useTerminal((s) => s.operator)
  const lastFastEventAt = useTerminal((s) => s.lastFastEventAt)
  const nowTick = useTerminal((s) => s.nowTick)
  const lastError = useTerminal((s) => s.lastError)
  const { phase0, engineMute } = useTerminal((s) => effectivePhase0(s))

  const fastLive = lastFastEventAt > 0 && nowTick - lastFastEventAt <= 5
  const marker = si?.session_marker ?? 'HORS_SESSION'
  const mode = si?.operational_mode ?? 'PRE_SESSION'

  return (
    <header className="flex h-9 shrink-0 items-center gap-3 border-b border-term-border bg-term-panel px-2">
      <span className="text-sm font-black tracking-widest text-router">CHOLISMO</span>
      <Clocks />
      <Badge variant={marker === 'HORS_SESSION' ? 'red' : 'yellow'} title="Marqueur de session">
        {MARKER_LABELS[marker]}
      </Badge>

      {/* Sélecteur 3 modes */}
      <div className="flex overflow-hidden rounded-sm border border-term-border" role="tablist" aria-label="Mode opérationnel">
        {MODES.map((m) => (
          <button key={m} role="tab" aria-selected={mode === m}
            className={cn('px-2 py-0.5 text-xxs font-semibold uppercase',
              mode === m ? 'bg-term-grid text-term-text' : 'text-term-dim hover:text-term-text')}
            onClick={() => { void api.setMode(m).catch(() => undefined) }}>
            {MODE_LABELS[m]}
          </button>
        ))}
      </div>

      {/* PHASE 0 GÉANT — reflet du moteur déterministe, l'UI n'override jamais */}
      <div
        className={cn(
          'flex h-full items-center gap-2 border-x-2 px-4 text-lg font-black tracking-widest',
          phase0 === 'OPEN'
            ? 'border-risk-green bg-risk-green/10 text-risk-green'
            : 'border-risk-red bg-risk-red/10 text-risk-red',
        )}
        title={engineMute ? 'Canal moteur muet > 5 s — fail-closed' : 'Moteur de règles déterministe Phase 0'}
        aria-live="polite"
      >
        {phase0 === 'OPEN' ? <LockOpen size={16} aria-hidden /> : <Lock size={16} aria-hidden />}
        PHASE 0 · {phase0 === 'OPEN' ? 'OUVERT' : 'BLOQUÉ'}
        {engineMute && <span className="text-xxs font-semibold text-risk-red">(MOTEUR MUET)</span>}
      </div>

      <MasterGlyph />
      <span className="text-xxs text-term-dim" title="Avis Groq — advisory seulement, jamais le verrou (CLAUDE §2.2)">
        GROQ: {si?.phase0_advisory ?? 'UNAVAILABLE'}
      </span>

      <div className="ml-auto flex items-center gap-3">
        {lastError && <span className="max-w-72 truncate text-xxs text-risk-red" title={lastError}>⚠ {lastError}</span>}
        <span className={cn('inline-flex items-center gap-1 text-xxs', fastLive ? 'text-risk-green' : 'text-risk-red')}
          title="Canal SSE rapide">
          {fastLive ? <RadioTower size={11} aria-hidden /> : <Radio size={11} aria-hidden />}
          {fastLive ? 'FLUX LIVE' : 'FLUX MUET'}
        </span>
        <Badge variant={operator === 'SONY' ? 'sony' : 'youssef'} title="Opérateur de cette instance (un par instance — CLAUDE §9)">
          {operator}
        </Badge>
        <Button variant="ghost" size="default"
          onClick={() => useTerminal.getState().set({ selfcheckOpen: true })}
          title="Self-check cognitif C5 (touche S)">
          C5
        </Button>
      </div>
    </header>
  )
}
