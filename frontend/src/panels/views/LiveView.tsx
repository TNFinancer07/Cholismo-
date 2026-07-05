/** Vue MODE LIVE (cholismo_unified Phase B, D-023) — couche analytique en langage clair.
 *
 *  Lecture marché 3 statuts + dialogue ADVISORY : les réponses viennent du répondeur
 *  DÉTERMINISTE serveur (règles pures sur le schéma, zéro LLM dans le hot path,
 *  CLAUDE §2.8) — « Mode Live propose, le RMS dispose », jamais d'override.
 *
 *  Optimisé : les tuiles VIX/CHOP/CVD/GEX lisent le store SSE existant par sélecteurs
 *  étroits (aucun canal ni polling supplémentaire) ; la lecture serveur est rafraîchie
 *  au cycle configuré (settings live.cycle_seconds, cadence du mock : 3 min en fenêtre,
 *  ralentie hors fenêtre) + event-driven quand un seuil est franchi côté client. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { MessageSquareText, Radio, Send, ShieldCheck } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtGex, fmtNum, fmtSigned, fmtTs } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { MetaValue } from '@/components/MetaValue'
import { Panel } from '@/components/ui/panel'
import { RiskGlyph, type RiskLevel } from '@/components/RiskGlyph'
import { Sparkline } from '@/components/Sparkline'
import type { LiveAnswer, LiveContextPayload } from '@/types/schema'

const LEVEL_TO_GLYPH: Record<string, RiskLevel> = { VERT: 'VERT', AMBRE: 'JAUNE', ROUGE: 'ROUGE' }

/** Bucket de seuils Phase 0 : un changement de bucket = re-lecture immédiate
 *  (event-driven du mock) sans re-render superflu entre les ticks. */
function thresholdBucket(vix: number | null, chop: number | null, blocked: boolean): string {
  const vixZone = vix === null ? 'x' : vix > 30 ? '2' : vix > 22 ? '1' : '0'
  const chopZone = chop === null ? 'x' : chop >= 61.8 ? '2' : chop > 55 ? '1' : '0'
  return `${vixZone}${chopZone}${blocked ? 'B' : 'O'}`
}

interface ChatMsg { who: 'user' | 'agent'; text: string; glossary?: string | null; ts: number }

function useLiveContext() {
  const [data, setData] = useState<LiveContextPayload | null>(null)
  const refresh = useCallback(async () => {
    try { setData(await api.liveContext() as LiveContextPayload) } catch { /* bandeau muet couvre */ }
  }, [])

  const vix = useTerminal((s) => {
    const v = s.s2_state?.cascade.vix.value
    return typeof v === 'number' ? v : null
  })
  const chop = useTerminal((s) => {
    const v = s.s1_state?.chop.value
    return typeof v === 'number' ? v : null
  })
  const blocked = useTerminal((s) => s.session_identity?.phase0 !== 'OPEN')
  const bucket = thresholdBucket(vix, chop, blocked)

  useEffect(() => { void refresh() }, [refresh, bucket]) // event-driven sur franchissement
  useEffect(() => {
    const inWindow = data?.context.session_window !== 'off_window'
    const period = (inWindow ? data?.cycle_seconds : data?.cycle_offwindow_seconds) ?? 180
    const timer = window.setInterval(() => void refresh(), Math.max(30, period) * 1000)
    return () => window.clearInterval(timer)
  }, [refresh, data?.cycle_seconds, data?.cycle_offwindow_seconds, data?.context.session_window])
  return data
}

const READING_TONES: Record<string, string> = {
  VERT: 'border-risk-green/50 bg-risk-green/5',
  AMBRE: 'border-risk-yellow/50 bg-risk-yellow/5',
  ROUGE: 'border-risk-red/60 bg-risk-red/5',
}

function MetricTile({ label, seriesKey, children }: {
  label: string; seriesKey?: string; children: React.ReactNode
}) {
  return (
    <div className="border border-term-border bg-term-panel2 px-1.5 py-1">
      <div className="flex items-center justify-between">
        <span className="text-xxs uppercase text-term-faint">{label}</span>
        {seriesKey && <Sparkline seriesKey={seriesKey} width={54} height={12} stroke="auto" />}
      </div>
      <div className="font-mono text-sm font-bold tabular-nums text-term-text">{children}</div>
    </div>
  )
}

/** Pipeline du cycle A→D (cholismo_unified) — reflet du mode opérationnel réel. */
function CyclePipeline() {
  const mode = useTerminal((s) => s.session_identity?.operational_mode ?? 'PRE_SESSION')
  const steps = [
    { key: 'PRE_SESSION', code: 'A', label: 'Pré-session', detail: 'ingestion · Phase 0 · scoring' },
    { key: 'LIVE', code: 'B', label: 'Live · Mode Live', detail: 'lecture + RMS + Go/No-Go' },
    { key: 'POST_SESSION', code: 'C', label: 'Post-session', detail: 'récon CSV · journal · scores' },
    { key: 'AUDIT', code: 'D', label: 'Persistance & audit', detail: 'event store · Gemini / 20 trades' },
  ]
  return (
    <div className="flex overflow-hidden border border-term-border" role="list"
      aria-label="cycle opérationnel A→D">
      {steps.map((step) => (
        <div key={step.key} role="listitem"
          className={cn('flex-1 border-r border-term-border px-2 py-1 last:border-r-0',
            mode === step.key && 'bg-term-panel2')}>
          <span className={cn('font-mono text-xxs font-black',
            mode === step.key ? 'text-router' : 'text-term-faint')}>{step.code}</span>
          <span className={cn('ml-1 text-xxs font-semibold',
            mode === step.key ? 'text-term-text' : 'text-term-dim')}>{step.label}</span>
          <p className="truncate font-mono text-xxs text-term-faint">{step.detail}</p>
        </div>
      ))}
    </div>
  )
}

function ChatPanel({ suggestions }: { suggestions: string[] }) {
  const operator = useTerminal((s) => s.operator)
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages])

  const send = useCallback(async (question: string) => {
    const q = question.trim()
    if (!q || busy) return
    setInput('')
    setBusy(true)
    setMessages((m) => [...m.slice(-49), { who: 'user', text: q, ts: Date.now() / 1000 }])
    try {
      const res = await api.liveAsk(q, operator) as LiveAnswer
      setMessages((m) => [...m.slice(-49),
        { who: 'agent', text: res.answer, glossary: res.glossary, ts: res.ts }])
    } catch (err) {
      setMessages((m) => [...m, { who: 'agent', ts: Date.now() / 1000,
        text: `indisponible : ${(err as Error).message}` }])
    } finally {
      setBusy(false)
    }
  }, [busy, operator])

  return (
    <Panel code="CHAT" title="Discussion avec l'agent" block="POST /live/ask — règles déterministes"
      className="min-h-0 flex-1"
      right={
        <span className="inline-flex items-center gap-1 text-xxs text-router">
          <ShieldCheck size={10} aria-hidden />ADVISORY · ne passe jamais d'ordre
        </span>
      }>
      <div className="flex h-full min-h-0 flex-col gap-1">
        <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1"
          aria-live="polite">
          {messages.length === 0 && (
            <p className="text-xxs text-term-faint">
              Pose une question sur l'état du marché — les réponses citent les valeurs réelles du
              schéma et exposent les conflits, sans jamais outrepasser un verrou.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={cn('max-w-[92%] border px-1.5 py-1 text-xs leading-snug',
              m.who === 'user'
                ? 'self-end border-sony/50 bg-sony/5 text-term-text'
                : 'self-start border-term-border bg-term-panel2 text-term-text')}>
              <span className="mb-0.5 block font-mono text-xxs uppercase tracking-wider text-term-faint">
                {m.who === 'user' ? 'vous' : 'mode live'} · {fmtTs(m.ts)}
              </span>
              {m.text}
              {m.glossary && (
                <span className="mt-1 block border border-sony/40 bg-sony/5 px-1 py-0.5 font-mono text-xxs text-sony">
                  {m.glossary}
                </span>
              )}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-0.5">
          {suggestions.map((s) => (
            <button key={s} disabled={busy}
              className="border border-term-border px-1.5 py-0.5 font-mono text-xxs text-term-dim hover:border-sony/50 hover:text-term-text disabled:opacity-50"
              onClick={() => void send(s)}>
              {s}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void send(input) }}
            placeholder="poser une question…" maxLength={500} disabled={busy}
            className="h-6 min-w-0 flex-1 border border-term-border bg-term-bg px-1.5 font-mono text-xs text-term-text placeholder:text-term-faint focus:border-sony/60 focus:outline-none disabled:opacity-50"
            aria-label="question au Mode Live" />
          <button onClick={() => void send(input)} disabled={busy || !input.trim()}
            className="inline-flex h-6 items-center gap-1 border border-sony/60 px-2 font-mono text-xxs font-bold uppercase text-sony hover:bg-sony/10 disabled:opacity-40">
            <Send size={10} aria-hidden />envoyer
          </button>
        </div>
      </div>
    </Panel>
  )
}

export function LiveView() {
  const live = useLiveContext()
  const s1 = useTerminal((s) => s.s1_state)
  const s2 = useTerminal((s) => s.s2_state)
  const bridge = useTerminal((s) => s.bridge_variables)
  const extras = useTerminal((s) => s.extras)
  const orchestrator = useTerminal((s) => s.orchestrator)
  const unifiedScore = useTerminal((s) => s.unified_signal_output?.score ?? null)

  const rms = extras?.rms ?? null

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-auto p-1.5">
      <CyclePipeline />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-1.5 lg:grid-cols-2">
        {/* ---- LECTURE MARCHÉ ---- */}
        <div className="flex min-h-0 flex-col gap-1.5">
          <Panel code="LIVE" title="Lecture marché" accent="sony"
            block="s1_state · s2_state · bridge_variables (SSE)"
            right={
              <span className="inline-flex items-center gap-1 font-mono text-xxs text-term-faint">
                <Radio size={10} aria-hidden />
                fenêtre {live?.context.session_window ?? '…'} · cycle {live ? fmtNum(live.cycle_seconds, 0) : '—'} s
              </span>
            }>
            {live ? (
              <div className={cn('border px-2 py-1.5', READING_TONES[live.reading.level])}
                role="status">
                <RiskGlyph level={LEVEL_TO_GLYPH[live.reading.level]} label={live.reading.title} size={13} />
                <p className="mt-1 text-xs leading-snug text-term-text">{live.reading.message}</p>
              </div>
            ) : (
              <p className="text-xxs text-term-faint">lecture en cours…</p>
            )}

            <div className="mt-1.5 grid grid-cols-2 gap-1">
              <MetricTile label="VIX" seriesKey="vix">
                <MetaValue meta={s2?.cascade.vix} render={(v) => fmtNum(v as number, 1)} />
              </MetricTile>
              <MetricTile label="CHOP(14)">
                <MetaValue meta={s1?.chop} render={(v) => fmtNum(v as number, 1)} />
              </MetricTile>
              <MetricTile label="CVD ES" seriesKey="cvd">
                <MetaValue meta={s1?.order_flow.cvd} render={(v) => fmtSigned(v as number, 0)} />
              </MetricTile>
              <MetricTile label="GEX" seriesKey="gex">
                <MetaValue meta={bridge?.gex} render={(v) => fmtGex(v as number)} />
              </MetricTile>
            </div>
          </Panel>

          <Panel code="RMS" title="RMS & console — 6 sources" block="orchestrateur (projection)">
            {orchestrator ? (
              <ul className="space-y-0.5">
                {Object.entries(orchestrator.sources).map(([name, src]) => (
                  <li key={name} className="flex items-center justify-between gap-2 border-b border-dashed border-term-grid pb-0.5 text-xxs last:border-b-0">
                    <span className="font-mono text-term-dim">{name}</span>
                    <span className="flex items-center gap-2 truncate">
                      <span className="truncate text-term-faint">{src.detail}</span>
                      <RiskGlyph level={src.level} size={10} />
                    </span>
                  </li>
                ))}
                <li className="flex items-center justify-between pt-1 text-xxs">
                  <span className="font-mono uppercase text-term-faint">
                    RMS {rms === null ? 'ABSENT (fail-closed)' : fmtNum(rms, 1)} · arbitrage
                  </span>
                  <span className="font-mono font-bold text-term-text">{orchestrator.action}</span>
                </li>
              </ul>
            ) : (
              <p className="text-xxs text-term-faint">console indisponible — fail-closed</p>
            )}
            <p className="mt-1 border-t border-term-border pt-1 text-xxs text-term-faint">
              <MessageSquareText size={10} className="mr-1 inline" aria-hidden />
              Mode Live PROPOSE, le RMS DISPOSE — cette vue ne peut ni armer ni couper une couche.
            </p>
          </Panel>
        </div>

        {/* ---- DIALOGUE ---- */}
        <ChatPanel suggestions={live?.suggestions ?? []} />
      </div>

      <p className="text-xxs text-term-faint">
        Signal unifié en lecture seule : {fmtNum(unifiedScore, 0)}
        {' '}· le Mode Live n'écrit rien, ne calcule aucun score et n'ouvre aucun chemin d'ordre
        (CLAUDE §2.1/§2.8) — réponses = règles déterministes serveur sur le schéma live.
      </p>
    </div>
  )
}
