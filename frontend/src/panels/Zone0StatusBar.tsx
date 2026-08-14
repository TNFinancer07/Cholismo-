/** ZONE 0 — barre de statut (`session_identity`). Horloge double Montréal+CET, marqueur de
 *  session (teinte le fond via App), 3 modes, PHASE 0 GÉANT (reflet du moteur déterministe,
 *  jamais overridable ici), glyphe état maître, badge opérateur. */
import { CalendarClock, Lock, LockOpen, PauseOctagon, Radio, RadioTower, ShieldAlert, ShieldCheck, ShieldHalf, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { fmtClock } from '@/lib/format'
import { AudioStatusIndicator } from '@/lib/audioAlerts'
import { cn } from '@/lib/utils'
import { effectivePhase0, MODES, serverNow, useTerminal } from '@/store/terminal'

// durée compacte : 1h04 / 04m30s (valeur absolue ; le sens « dans / publiée +X » est porté à part)
function fmtDur(s: number): string {
  if (!Number.isFinite(s)) return '—'
  const a = Math.abs(Math.round(s)), m = Math.floor(a / 60), h = Math.floor(m / 60)
  return h > 0 ? `${h}h${String(m % 60).padStart(2, '0')}` : `${m}m${String(a % 60).padStart(2, '0')}s`
}

/** Badge de régime MACRO (`macro_risk`, D-040) — reflète le Risk Guard déterministe (câblé à
 *  Phase 0 §2.2). Régime encodé par COULEUR + GLYPHE + TEXTE (jamais la couleur seule §3).
 *  Countdown dérivé côté client (event.ts − serverNow) → cohérent avec les autres compte-à-rebours. */
/** Porte F0 macro (D-050) — l'opérateur voit IMMÉDIATEMENT si le verrou news est actif :
 *  jamais un verrou invisible. Icône + texte, jamais la couleur seule (§3). Absent (null) =
 *  couche news non câblée → pas de porte, rien à afficher (honnête). */
function NewsGateBadge() {
  const ns = useTerminal((s) => s.extras?.news_state)
  if (ns == null) return null
  const cfg: Record<string, { icon: string; txt: string; cls: string; hint: string }> = {
    NORMAL: { icon: '●', txt: 'F0 · RAS', cls: 'text-term-dim',
      hint: 'Porte F0 (news macro) armée — aucun événement USD à fort impact à portée.' },
    WARNING: { icon: '⚠', txt: 'F0 · NEWS ≤ 15 MIN', cls: 'text-risk-yellow font-semibold',
      hint: 'Événement USD à fort impact dans moins de 15 min — le verrou tombera à T−2 min.' },
    HARD_LOCK: { icon: '⛔', txt: 'F0 · NEWS LOCK', cls: 'text-risk-red font-black',
      hint: 'HARD LOCK : fenêtre T−2/T+2 d’une publication USD à fort impact — aucune proposition LSR n’est émise.' },
    SAFETY_UNKNOWN: { icon: '?', txt: 'F0 · CALENDRIER INCONNU', cls: 'text-stale font-semibold',
      hint: 'Calendrier macro illisible ou fossile — la couche est AVEUGLE : aucune proposition LSR n’est émise (fail-closed).' },
  }
  const c = cfg[ns] ?? cfg.SAFETY_UNKNOWN
  return (
    <span className={cn('inline-flex items-center gap-1 text-xxs', c.cls)} title={c.hint}>
      <span aria-hidden>{c.icon}</span>{c.txt}
    </span>
  )
}


function MacroRegimeBadge() {
  const mr = useTerminal((s) => s.macro_risk?.value)
  const now = useTerminal((s) => serverNow(s))
  if (!mr) return null
  const regime = mr.regime
  // critique (PAUSED/WARNING) = fond + bordure + label bien visible ; NORMAL = discret (pas de
  // fond, pas de bordure) pour ne pas surcharger. PAUSED pulse pour attirer l'œil immédiatement.
  const cfg = regime === 'EXECUTION_PAUSED'
    ? { cls: 'border-x border-risk-red bg-risk-red/20 text-risk-red', Icon: PauseOctagon, label: 'EXECUTION_PAUSED', strong: true, pulse: true }
    : regime === 'WARNING'
      ? { cls: 'border-x border-risk-yellow bg-risk-yellow/15 text-risk-yellow', Icon: TriangleAlert, label: 'WARNING', strong: true, pulse: false }
      : { cls: 'text-risk-green/75', Icon: CalendarClock, label: 'NORMAL', strong: false, pulse: false }
  const ev = mr.event
  const delta = ev && Number.isFinite(ev.ts) ? ev.ts - now : null
  const when = delta === null ? '' : delta >= 0 ? `dans ${fmtDur(delta)}` : `publiée +${fmtDur(delta)}`
  return (
    <div className={cn('flex h-full items-center gap-1.5 px-2 text-xxs font-bold tabular-nums', cfg.cls)}
      title="Régime macro (Risk Guard déterministe, câblé à Phase 0 — CLAUDE §2.2/§2.4)" aria-live="polite">
      <cfg.Icon size={cfg.strong ? 14 : 13} aria-hidden className={cfg.pulse ? 'animate-pulse' : undefined} />
      {ev?.name && <span className="font-mono font-normal">{ev.name}{when && ` ${when}`}</span>}
      {cfg.strong && <span className="tracking-wide">· {cfg.label}</span>}
    </div>
  )
}

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

      <MacroRegimeBadge />
      <NewsGateBadge />
      <MasterGlyph />
      <span className="text-xxs text-term-dim" title="Avis Groq — advisory seulement, jamais le verrou (CLAUDE §2.2)">
        GROQ: {si?.phase0_advisory ?? 'UNAVAILABLE'}
      </span>

      <div className="ml-auto flex items-center gap-3">
        {/* Permanent : un silence ambigu annulerait toute la garde de fraîcheur (D-114/115). */}
        <AudioStatusIndicator />
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
