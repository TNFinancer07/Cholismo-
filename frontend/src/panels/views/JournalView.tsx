/** Onglet JOURNAL — transposition terminal de reference/journal/tradingjournal.html
 *  (« Journal de Session — Sony & Youssef », D-022). Trois sous-vues : Session ·
 *  Historique & agrégats · Automatisation. Philosophie event-sourced du terminal :
 *  brouillon Redis modifiable → « Clôturer & verrouiller » = entrée APPEND-ONLY (SQLite),
 *  plus jamais modifiable. Lockout 2 pertes → 24 h dérivé, jamais stocké. */
import { useCallback, useEffect, useState } from 'react'
import { BookOpenText, FileDown, Lock, Plus, Send, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtNum, fmtSigned, fmtTs } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { MetaValue } from '@/components/MetaValue'

// ---------- types (miroir de GET /journal) ----------

interface StrategyMeta { label: string; operator: string; seuil: number | null; accent: string }
interface Draft {
  draft_id: string; strategy_id: string; operator: string; created_ts: number; trade_num: number
  [key: string]: unknown
}
interface LockedEntry extends Record<string, unknown> {
  id: string; ts: number; strategy_id: string; trade_num: number
}
interface JournalData {
  strategies: Record<string, StrategyMeta>
  exit_types: string[]
  paliers: string[]
  drafts: Draft[]
  entries: LockedEntry[]
  sessions: Record<string, unknown>[]
  sentiments: Record<string, { humeur: number; energie: number; confiance: number; facteurs: string; note: string }>
  aggregates: { total: Record<string, number | null>; by_day: { day: string; trades: number; r_total: number; wins: number }[] }
  lockout: { active: boolean; consecutive_losses: number; until_ts: number | null; rule: string }
  n8n: { url: string; api_key: string; enabled: boolean }
}

function useJournal() {
  const [data, setData] = useState<JournalData | null>(null)
  const refresh = useCallback(async () => {
    try { setData(await api.journal() as JournalData) } catch { /* bandeau flux couvre */ }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 8000)
    return () => window.clearInterval(timer)
  }, [refresh])
  return { data, refresh }
}

// ---------- petits contrôles de formulaire ----------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate text-xxs uppercase text-term-faint">{label}</span>
      {children}
    </label>
  )
}

const INPUT_CLS = 'h-6 w-full border border-term-border bg-term-bg px-1 text-xs tabular-nums text-term-text focus:border-router focus:outline-none disabled:opacity-50'

function Choice({ value, options, onChange, disabled }: {
  value: unknown; options: { v: unknown; label: string; cls?: string }[]
  onChange: (v: unknown) => void; disabled?: boolean
}) {
  return (
    <div className="flex flex-wrap gap-0.5">
      {options.map((option) => (
        <button key={String(option.v)} disabled={disabled}
          className={cn('border px-1.5 py-0.5 text-xxs font-semibold uppercase disabled:opacity-50',
            value === option.v
              ? option.cls ?? 'border-router text-router'
              : 'border-term-border text-term-dim hover:text-term-text')}
          onClick={() => onChange(option.v)}>
          {option.label}
        </button>
      ))}
    </div>
  )
}

// ---------- fiche de trade ----------

function TradeCard({ draft, locked, meta, exitTypes, paliers, onMutate }: {
  draft: Draft | LockedEntry; locked: boolean; meta: StrategyMeta
  exitTypes: string[]; paliers: string[]; onMutate: () => void
}) {
  const [fields, setFields] = useState<Record<string, unknown>>({ ...draft })
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(!locked)
  useEffect(() => { setFields({ ...draft }) }, [draft])

  const draftId = (draft as Draft).draft_id
  async function save(patch: Record<string, unknown>) {
    if (locked) return
    setFields((f) => ({ ...f, ...patch }))
    try {
      await api.journalUpdateDraft(draftId, patch)
      setError(null)
    } catch (err) { setError((err as Error).message) }
  }
  const num = (key: string) => (fields[key] === null || fields[key] === undefined ? '' : String(fields[key]))
  const numPatch = (key: string, raw: string) =>
    save({ [key]: raw.trim() === '' ? null : Number(raw.replace(',', '.')) })

  const r = fields.resultat_r as number | null
  const accent = meta.accent === 'youssef' ? 'text-youssef' : 'text-sony'

  return (
    <div className={cn('border bg-term-panel2', locked ? 'border-term-border' : 'border-router/40')}>
      <button className="flex w-full items-center justify-between gap-2 px-1.5 py-1"
        onClick={() => setOpen((o) => !o)}>
        <span className="flex min-w-0 items-center gap-1.5">
          {locked && <Lock size={10} className="shrink-0 text-term-dim" aria-label="verrouillé" />}
          <span className={cn('shrink-0 text-xxs font-bold', accent)}>#{String(draft.trade_num)}</span>
          <span className="truncate text-xxs text-term-dim">
            {locked ? fmtTs(draft.ts as number) : 'BROUILLON'} · {String(fields.direction ?? '—')}
            {fields.type_sortie ? ` · ${fields.type_sortie}` : ''}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {typeof r === 'number' && (
            <span className={cn('text-xs font-bold tabular-nums',
              r > 0 ? 'text-risk-green' : r < 0 ? 'text-risk-red' : 'text-term-dim')}>
              {fmtSigned(r, 2)}R
            </span>
          )}
          {fields.erreur_type ? <Badge variant="red">TYPE {String(fields.erreur_type)}</Badge> : null}
          {locked ? <Badge variant="default">VERROUILLÉ</Badge> : <Badge variant="router">ÉDITABLE</Badge>}
        </span>
      </button>

      {open && (
        <div className="border-t border-term-grid p-1.5">
          <div className="grid grid-cols-4 gap-1.5">
            <Field label="Direction">
              <Choice disabled={locked} value={fields.direction}
                options={[{ v: 'LONG', label: 'LONG', cls: 'border-risk-green text-risk-green' },
                          { v: 'SHORT', label: 'SHORT', cls: 'border-risk-red text-risk-red' }]}
                onChange={(v) => void save({ direction: v })} />
            </Field>
            <Field label="Prix déclencheur">
              <input className={INPUT_CLS} disabled={locked} defaultValue={num('trigger_price')}
                onBlur={(e) => void numPatch('trigger_price', e.target.value)} />
            </Field>
            <Field label="Prix de sortie">
              <input className={INPUT_CLS} disabled={locked} defaultValue={num('exit_price')}
                onBlur={(e) => void numPatch('exit_price', e.target.value)} />
            </Field>
            <Field label="Taille finale %">
              <input className={INPUT_CLS} disabled={locked} defaultValue={num('taille_finale_pct')}
                onBlur={(e) => void numPatch('taille_finale_pct', e.target.value)} />
            </Field>
            <Field label="CHOP au trade (prérempli)">
              <input className={INPUT_CLS} disabled={locked} defaultValue={num('chop')}
                onBlur={(e) => void numPatch('chop', e.target.value)} />
            </Field>
            <Field label="VIX au trade (prérempli)">
              <input className={INPUT_CLS} disabled={locked} defaultValue={num('vix')}
                onBlur={(e) => void numPatch('vix', e.target.value)} />
            </Field>
            <Field label="Corr NQ/ES (manuel)">
              <input className={INPUT_CLS} disabled={locked} defaultValue={num('nq_es_corr')}
                onBlur={(e) => void numPatch('nq_es_corr', e.target.value)} />
            </Field>
            <Field label={meta.seuil ? `Score global (seuil ≥ ${meta.seuil})` : 'Conviction /10'}>
              <input className={INPUT_CLS} disabled={locked}
                defaultValue={meta.seuil ? num('score_global') : num('conviction')}
                onBlur={(e) => void numPatch(meta.seuil ? 'score_global' : 'conviction', e.target.value)} />
            </Field>
            <Field label="Type de sortie (hiérarchie §06)">
              <select className={INPUT_CLS} disabled={locked} value={String(fields.type_sortie ?? '')}
                onChange={(e) => void save({ type_sortie: e.target.value || null })}>
                <option value="">—</option>
                {exitTypes.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="Palier atteint avant sortie">
              <select className={INPUT_CLS} disabled={locked} value={String(fields.palier_profit_atteint ?? '')}
                onChange={(e) => void save({ palier_profit_atteint: e.target.value || null })}>
                <option value="">—</option>
                {paliers.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </Field>
            <Field label="Distance SL respectée ?">
              <Choice disabled={locked} value={fields.sl_distance_respectee}
                options={[{ v: true, label: 'OUI', cls: 'border-risk-green text-risk-green' },
                          { v: false, label: 'NON', cls: 'border-risk-red text-risk-red' }]}
                onChange={(v) => void save({ sl_distance_respectee: v, ...(v === false ? { erreur_type: 'A' } : {}) })} />
            </Field>
            <Field label="Sortie justifiée ? (friction #2)">
              <Choice disabled={locked} value={fields.sortie_justifiee}
                options={[{ v: true, label: 'Correcte', cls: 'border-risk-green text-risk-green' },
                          { v: false, label: 'Incorrecte', cls: 'border-risk-red text-risk-red' }]}
                onChange={(v) => void save({ sortie_justifiee: v })} />
            </Field>
            <Field label="Résultat (R)">
              <input className={INPUT_CLS} disabled={locked} defaultValue={num('resultat_r')}
                onBlur={(e) => void numPatch('resultat_r', e.target.value)} />
            </Field>
            <Field label="Erreur (si perdant)">
              <Choice disabled={locked} value={fields.erreur_type}
                options={[{ v: 'A', label: 'A discipline' }, { v: 'B', label: 'B marché' },
                          { v: 'C', label: 'C exécution' }, { v: null, label: '—' }]}
                onChange={(v) => void save({ erreur_type: v })} />
            </Field>
            {meta.operator === 'YOUSSEF' && (
              <Field label="Feu N4 (dernier contrôle)">
                <Choice disabled={locked} value={fields.validation_n4}
                  options={[{ v: 'GO', label: 'GO', cls: 'border-risk-green text-risk-green' },
                            { v: 'NO_GO', label: 'NO-GO', cls: 'border-risk-red text-risk-red' }]}
                  onChange={(v) => void save({ validation_n4: v })} />
              </Field>
            )}
            <Field label={`État émotionnel : ${String(fields.etat_emotionnel ?? '—')} (1 calme · 5 stress)`}>
              <input type="range" min={1} max={5} step={1} disabled={locked}
                className="h-1 accent-[#f0b429]"
                value={Number(fields.etat_emotionnel ?? 3)}
                onChange={(e) => setFields((f) => ({ ...f, etat_emotionnel: Number(e.target.value) }))}
                onMouseUp={() => void save({ etat_emotionnel: fields.etat_emotionnel ?? 3 })} />
            </Field>
          </div>

          <div className="mt-1.5 grid grid-cols-2 gap-1.5">
            <Field label="Thèse (avant l'entrée — après = rationalisation)">
              <textarea className={cn(INPUT_CLS, 'h-12 resize-none py-0.5 font-mono')} disabled={locked}
                defaultValue={String(fields.these ?? '')}
                onBlur={(e) => void save({ these: e.target.value })} />
            </Field>
            <Field label="Notes post-trade">
              <textarea className={cn(INPUT_CLS, 'h-12 resize-none py-0.5 font-mono')} disabled={locked}
                defaultValue={String(fields.notes ?? '')}
                onBlur={(e) => void save({ notes: e.target.value })} />
            </Field>
          </div>

          {error && <p className="mt-1 text-xxs text-risk-red">{error}</p>}
          {!locked && (
            <div className="mt-1.5 flex justify-between">
              <Button variant="ghost" onClick={async () => {
                await api.journalDeleteDraft(draftId).catch(() => undefined); onMutate()
              }}><Trash2 size={10} aria-hidden /> Supprimer (brouillon)</Button>
              <Button variant="router" onClick={async () => {
                try { await api.journalLockDraft(draftId); setError(null); onMutate() }
                catch (err) { setError((err as Error).message) }
              }}><Lock size={10} aria-hidden /> Clôturer &amp; verrouiller</Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------- sentiment pré/post-session ----------

function SentimentBlock({ phase, data, onSaved }: {
  phase: 'PRE' | 'POST'; data: JournalData; onSaved: () => void
}) {
  return (
    <Panel code={phase === 'PRE' ? 'SENT·PRE' : 'SENT·POST'}
      title={phase === 'PRE' ? 'Sentiment pré-session' : 'Sentiment post-session'}
      block="journal (Redis → figé à la clôture de session)">
      <div className="grid grid-cols-2 gap-2">
        {(['SONY', 'YOUSSEF'] as const).map((operator) => {
          const existing = data.sentiments[`${phase}:${operator}`]
          return <SentimentForm key={operator} phase={phase} operator={operator}
            existing={existing} onSaved={onSaved} />
        })}
      </div>
    </Panel>
  )
}

function SentimentForm({ phase, operator, existing, onSaved }: {
  phase: 'PRE' | 'POST'; operator: 'SONY' | 'YOUSSEF'
  existing?: { humeur: number; energie: number; confiance: number; facteurs: string; note: string }
  onSaved: () => void
}) {
  const [values, setValues] = useState({ humeur: existing?.humeur ?? 3, energie: existing?.energie ?? 3,
    confiance: existing?.confiance ?? 3, facteurs: existing?.facteurs ?? '', note: existing?.note ?? '' })
  useEffect(() => {
    if (existing) setValues({ ...existing })
  }, [existing])
  return (
    <div className={cn('border-l-2 pl-1.5', operator === 'SONY' ? 'border-sony/60' : 'border-youssef/60')}>
      <div className={cn('text-xxs font-bold uppercase', operator === 'SONY' ? 'text-sony' : 'text-youssef')}>
        {operator} {existing && <span className="text-risk-green">✓ renseigné</span>}
      </div>
      {(['humeur', 'energie', 'confiance'] as const).map((key) => (
        <label key={key} className="flex items-center gap-2 text-xxs">
          <span className="w-16 uppercase text-term-dim">{key}</span>
          <input type="range" min={1} max={5} className="h-1 flex-1 accent-[#f0b429]"
            value={values[key]}
            onChange={(e) => setValues((v) => ({ ...v, [key]: Number(e.target.value) }))} />
          <span className="w-4 text-right tabular-nums">{values[key]}</span>
        </label>
      ))}
      <input className={cn(INPUT_CLS, 'mt-0.5')} placeholder="facteurs : sommeil, externe, P&L récent…"
        value={values.facteurs}
        onChange={(e) => setValues((v) => ({ ...v, facteurs: e.target.value }))} />
      <div className="mt-0.5 flex gap-1">
        <input className={INPUT_CLS} placeholder="note libre"
          value={values.note}
          onChange={(e) => setValues((v) => ({ ...v, note: e.target.value }))} />
        <Button variant="ghost" onClick={async () => {
          await api.journalSentiment({ phase, operator, ...values }).catch(() => undefined)
          onSaved()
        }}>OK</Button>
      </div>
    </div>
  )
}

// ---------- sous-vues ----------

function SessionTab({ data, refresh }: { data: JournalData; refresh: () => void }) {
  const s1 = useTerminal((s) => s.s1_state)
  const s2 = useTerminal((s) => s.s2_state)
  const bridge = useTerminal((s) => s.bridge_variables)
  const operator = useTerminal((s) => s.operator)
  const [activeStrategy, setActiveStrategy] = useState('SVS')
  const meta = data.strategies[activeStrategy]
  const drafts = data.drafts.filter((d) => d.strategy_id === activeStrategy)
  const today = new Date().toISOString().slice(0, 10)
  const lockedToday = data.entries.filter((e) => e.strategy_id === activeStrategy
    && new Date(e.ts * 1000).toISOString().slice(0, 10) === today)
  const rToday = data.entries
    .filter((e) => new Date(e.ts * 1000).toISOString().slice(0, 10) === today)
    .reduce((sum, e) => sum + (Number(e.resultat_r) || 0), 0)

  function exportData(format: 'csv' | 'json') {
    const rows = data.entries
    let blob: Blob
    if (format === 'json') {
      blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' })
    } else {
      const cols = ['ts', 'strategy_id', 'operator', 'trade_num', 'direction', 'trigger_price',
        'exit_price', 'chop', 'vix', 'score_global', 'taille_finale_pct', 'type_sortie',
        'palier_profit_atteint', 'sortie_justifiee', 'sl_distance_respectee', 'resultat_r',
        'erreur_type', 'conviction', 'validation_n4', 'etat_emotionnel', 'these', 'notes']
      const csv = [cols.join(';'), ...rows.map((row) =>
        cols.map((c) => JSON.stringify(row[c] ?? '')).join(';'))].join('\n')
      blob = new Blob([csv], { type: 'text/csv' })
    }
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `journal-${today}.${format}`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[280px_1fr] gap-1.5 overflow-hidden">
      {/* barre latérale — contexte + lockout + export */}
      <div className="flex min-h-0 flex-col gap-1.5 overflow-auto">
        <Panel code="CTX" title="Contexte de session" block="schéma live">
          <div className="space-y-0.5 text-xs">
            <div className="flex justify-between"><span className="text-term-dim">VIX</span>
              <MetaValue meta={s2?.cascade.vix} render={(v) => fmtNum(v as number, 2)} /></div>
            <div className="flex justify-between"><span className="text-term-dim">VVIX</span>
              <MetaValue meta={bridge?.vvix} render={(v) => fmtNum(v as number, 1)} /></div>
            <div className="flex justify-between"><span className="text-term-dim">CHOP(14)</span>
              <MetaValue meta={s1?.chop} render={(v) => fmtNum(v as number, 1)} /></div>
          </div>
          <table className="mt-1.5 w-full border-collapse text-xxs tabular-nums">
            <thead><tr className="border-b border-term-border text-left uppercase text-term-faint">
              <th className="font-semibold">CI — référence</th><th className="font-semibold">MR buffer</th><th className="font-semibold">SVS</th></tr></thead>
            <tbody className="text-term-dim">
              <tr><td>&gt; 90</td><td>2 ticks</td><td rowSpan={3} className="text-risk-red">⛔ bloquant</td></tr>
              <tr><td>75-90</td><td>5 ticks</td></tr>
              <tr><td>61.8-75</td><td>3 ticks</td></tr>
              <tr><td>&lt; 61.8</td><td className="text-risk-red">G4 FAIL ⛔</td><td className="text-risk-green">OK si &lt;50</td></tr>
            </tbody>
          </table>
        </Panel>

        <Panel code="STAT" title="Session courante" block="projection journal">
          <div className="flex justify-between text-xs">
            <span className="text-term-dim">R total (jour)</span>
            <b className={cn('tabular-nums', rToday > 0 ? 'text-risk-green' : rToday < 0 ? 'text-risk-red' : '')}>
              {fmtSigned(rToday, 2)}R
            </b>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-term-dim">Pertes consécutives</span>
            <b className={cn('tabular-nums', data.lockout.consecutive_losses >= 2 ? 'text-risk-red' : '')}>
              {data.lockout.consecutive_losses}
            </b>
          </div>
          {data.lockout.active ? (
            <p className="mt-1 border border-risk-red bg-risk-red/10 px-1.5 py-0.5 text-xxs font-bold text-risk-red">
              ⛔ LOCKOUT — {data.lockout.rule}
              {data.lockout.until_ts && <> · jusqu'à {fmtTs(data.lockout.until_ts)}</>}
            </p>
          ) : (
            <p className="mt-1 text-xxs text-term-faint">aucun lockout dérivé actif ({data.lockout.rule})</p>
          )}
        </Panel>

        <Panel code="EXP" title="Export" block="entrées verrouillées">
          <div className="flex gap-1.5">
            <Button variant="ghost" className="flex-1" onClick={() => exportData('csv')}>
              <FileDown size={10} aria-hidden /> CSV</Button>
            <Button variant="ghost" className="flex-1" onClick={() => exportData('json')}>
              <FileDown size={10} aria-hidden /> JSON</Button>
          </div>
        </Panel>
      </div>

      {/* colonne principale */}
      <div className="flex min-h-0 flex-col gap-1.5 overflow-auto pr-1">
        <SentimentBlock phase="PRE" data={data} onSaved={refresh} />

        <Panel code="TRADES" title="Fiches de trade" block="brouillon Redis → entrée append-only"
          right={
            <Button variant="router" onClick={async () => {
              await api.journalCreateDraft(activeStrategy, meta.operator || operator).catch(() => undefined)
              refresh()
            }}><Plus size={10} aria-hidden /> Nouveau trade</Button>
          }>
          <div className="mb-1.5 flex gap-1" role="tablist" aria-label="Stratégie">
            {Object.entries(data.strategies).map(([id, s]) => (
              <button key={id} role="tab" aria-selected={activeStrategy === id}
                className={cn('border px-2 py-0.5 text-xxs font-semibold uppercase',
                  activeStrategy === id
                    ? s.accent === 'youssef' ? 'border-youssef text-youssef' : 'border-sony text-sony'
                    : 'border-term-border text-term-dim hover:text-term-text')}
                onClick={() => setActiveStrategy(id)}>
                {s.label.split('—')[0].trim()}
              </button>
            ))}
          </div>
          <p className="mb-1 text-xxs text-term-faint">
            {meta.label} · opérateur {meta.operator}
            {meta.seuil && <> · seuil ≥ {meta.seuil}/100</>} · CHOP/VIX préremplis depuis le schéma live
          </p>
          <div className="space-y-1">
            {drafts.map((d) => (
              <TradeCard key={d.draft_id} draft={d} locked={false} meta={meta}
                exitTypes={data.exit_types} paliers={data.paliers} onMutate={refresh} />
            ))}
            {lockedToday.map((e) => (
              <TradeCard key={e.id} draft={e as never} locked meta={meta}
                exitTypes={data.exit_types} paliers={data.paliers} onMutate={refresh} />
            ))}
            {drafts.length === 0 && lockedToday.length === 0 && (
              <p className="py-2 text-center text-xxs text-term-faint">
                aucun trade journalisé pour {meta.label.split('—')[0].trim()} aujourd'hui
              </p>
            )}
          </div>
        </Panel>

        <SentimentBlock phase="POST" data={data} onSaved={refresh} />
      </div>
    </div>
  )
}

function HistoryTab({ data }: { data: JournalData }) {
  const t = data.aggregates.total
  const stats: [string, string, string?][] = [
    ['Jours', String(t.days ?? 0)],
    ['Trades', String(t.trades ?? 0)],
    ['R cumulé', fmtSigned(t.r_total as number, 2) + 'R', (t.r_total as number) >= 0 ? 'text-risk-green' : 'text-risk-red'],
    ['Winrate', t.winrate_pct === null ? '—' : `${t.winrate_pct} %`],
    ['Erreurs A', String(t.err_a ?? 0), (t.err_a as number) > 0 ? 'text-risk-red' : undefined],
    ['Erreurs B', String(t.err_b ?? 0)],
    ['Erreurs C', String(t.err_c ?? 0)],
    ['Sorties évaluées', String(t.early_evaluated ?? 0)],
    ['Sorties précoces non justifiées', String(t.early_unjustified ?? 0)],
    ['Taux friction #2', t.friction2_pct === null ? '—' : `${t.friction2_pct} %`,
      (t.friction2_pct as number) > 0 ? 'text-risk-yellow' : undefined],
  ]
  return (
    <div className="grid min-h-0 flex-1 grid-cols-2 gap-1.5 overflow-auto">
      <Panel code="AGG" title="Agrégats — toutes sessions" block="projection entrées verrouillées">
        <div className="grid grid-cols-2 gap-1">
          {stats.map(([label, value, cls]) => (
            <div key={label} className="border border-term-grid bg-term-panel2 px-1.5 py-1">
              <div className="text-xxs uppercase text-term-faint">{label}</div>
              <div className={cn('text-sm font-bold tabular-nums', cls)}>{value}</div>
            </div>
          ))}
        </div>
        <p className="mt-1.5 text-xxs text-term-faint">
          la friction #2 (sortie précoce sans règle §06 qui la justifie) devient visible et
          quantifiable ici — c'est le but du journal (reference/journal).
        </p>
      </Panel>
      <Panel code="JOURS" title="Détail par jour" block="projection entrées verrouillées">
        <table className="w-full border-collapse text-xxs tabular-nums">
          <thead><tr className="border-b border-term-border text-left uppercase text-term-faint">
            <th className="py-0.5 font-semibold">jour</th><th className="font-semibold">trades</th>
            <th className="font-semibold">wins</th><th className="font-semibold">R total</th></tr></thead>
          <tbody>
            {data.aggregates.by_day.length === 0 && (
              <tr><td colSpan={4} className="py-2 text-center text-term-faint">
                aucun trade clôturé — verrouille un trade pour alimenter les agrégats</td></tr>
            )}
            {data.aggregates.by_day.map((d) => (
              <tr key={d.day} className="border-b border-term-grid">
                <td className="py-0.5">{d.day}</td><td>{d.trades}</td><td>{d.wins}</td>
                <td className={d.r_total >= 0 ? 'text-risk-green' : 'text-risk-red'}>{fmtSigned(d.r_total, 2)}R</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.sessions.length > 0 && (
          <>
            <div className="mt-2 text-xxs uppercase text-term-faint">sessions clôturées (immuables)</div>
            {data.sessions.map((s) => (
              <div key={String(s.id)} className="flex justify-between border-b border-term-grid py-0.5 text-xxs">
                <span>{String(s.day)} · {String(s.trades)} trades</span>
                <span className="tabular-nums">{fmtSigned(Number(s.r_total), 2)}R</span>
              </div>
            ))}
          </>
        )}
      </Panel>
    </div>
  )
}

function AutomationTab({ data, refresh }: { data: JournalData; refresh: () => void }) {
  const [cfg, setCfg] = useState(data.n8n)
  useEffect(() => setCfg(data.n8n), [data.n8n])
  const [closed, setClosed] = useState<string | null>(null)
  return (
    <div className="grid min-h-0 flex-1 grid-cols-2 gap-1.5 overflow-auto">
      <Panel code="N8N" title="Webhooks n8n" block="config Redis · appels async loggés (ai_calls)">
        <Field label="URL du webhook n8n">
          <input className={INPUT_CLS} value={cfg.url} placeholder="http://n8n:5678/webhook/…"
            onChange={(e) => setCfg((c) => ({ ...c, url: e.target.value }))} />
        </Field>
        <Field label="X-API-Key (optionnel)">
          <input className={INPUT_CLS} value={cfg.api_key}
            onChange={(e) => setCfg((c) => ({ ...c, api_key: e.target.value }))} />
        </Field>
        <div className="mt-1 flex items-center justify-between">
          <Choice value={cfg.enabled}
            options={[{ v: true, label: 'Actif', cls: 'border-risk-green text-risk-green' },
                      { v: false, label: 'Inactif' }]}
            onChange={(v) => setCfg((c) => ({ ...c, enabled: v as boolean }))} />
          <Button variant="router" onClick={async () => {
            await api.journalSetN8n(cfg).catch(() => undefined); refresh()
          }}>Enregistrer</Button>
        </div>
        <div className="mt-2 border-t border-term-grid pt-1 text-xxs text-term-dim">
          <div className="mb-0.5 uppercase text-term-faint">événements</div>
          <div>✓ <b>trade_closed</b> — émis au verrouillage d'une fiche (payload complet)</div>
          <div>✓ <b>session_closed</b> — émis à la clôture de session (agrégats + sentiments)</div>
          <div className="text-term-faint">✎ trade_created · threshold_breached — non câblés (à brancher côté n8n)</div>
        </div>
      </Panel>
      <Panel code="CLOSE" title="Clôture de session" block="→ entrée session_closed append-only">
        <p className="text-xxs text-term-dim">
          Fige les sentiments pré/post et les agrégats du jour dans une entrée immuable,
          puis émet <b>session_closed</b> vers n8n (au NY close, pour le rapport de session).
        </p>
        <Button variant="router" className="mt-2 w-full" size="lg" onClick={async () => {
          const res = await api.journalCloseSession().catch(() => null) as { entry?: { day?: string } } | null
          setClosed(res?.entry?.day ?? null); refresh()
        }}>
          <Send size={11} aria-hidden /> Clôturer la session &amp; envoyer à n8n
        </Button>
        {closed && <p className="mt-1 text-center text-xxs text-risk-green">session {closed} clôturée (entrée immuable écrite)</p>}
      </Panel>
    </div>
  )
}

// ---------- vue principale ----------

export function JournalView() {
  const { data, refresh } = useJournal()
  const [tab, setTab] = useState<'SESSION' | 'HISTORIQUE' | 'AUTOMATISATION'>('SESSION')

  if (!data) {
    return <div className="grid flex-1 place-items-center text-xxs text-term-faint">chargement du journal…</div>
  }
  const t = data.aggregates.total

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1.5 p-1.5">
      <div className="flex h-7 shrink-0 items-center gap-3 border border-term-border bg-term-panel px-2">
        <span className="inline-flex items-center gap-1.5 text-xxs font-black uppercase tracking-widest text-router">
          <BookOpenText size={12} aria-hidden /> Journal de session — Sony &amp; Youssef
        </span>
        <div className="flex gap-1" role="tablist" aria-label="Sous-vue du journal">
          {(['SESSION', 'HISTORIQUE', 'AUTOMATISATION'] as const).map((k) => (
            <button key={k} role="tab" aria-selected={tab === k}
              className={cn('border-b-2 px-2 py-0.5 text-xxs font-semibold uppercase',
                tab === k ? 'border-router text-router' : 'border-transparent text-term-dim hover:text-term-text')}
              onClick={() => setTab(k)}>
              {k === 'HISTORIQUE' ? 'Historique & agrégats' : k.toLowerCase()}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3 text-xxs tabular-nums">
          <span>R total <b className={cn((t.r_total as number) >= 0 ? 'text-risk-green' : 'text-risk-red')}>
            {fmtSigned(t.r_total as number, 2)}R</b></span>
          <span>trades <b>{String(t.trades)}</b></span>
          <span>pertes conséc. <b className={data.lockout.consecutive_losses >= 2 ? 'text-risk-red' : ''}>
            {data.lockout.consecutive_losses}</b></span>
          {data.lockout.active && <Badge variant="red">⛔ LOCKOUT 24 h</Badge>}
        </div>
      </div>

      {tab === 'SESSION' && <SessionTab data={data} refresh={refresh} />}
      {tab === 'HISTORIQUE' && <HistoryTab data={data} />}
      {tab === 'AUTOMATISATION' && <AutomationTab data={data} refresh={refresh} />}
    </div>
  )
}
