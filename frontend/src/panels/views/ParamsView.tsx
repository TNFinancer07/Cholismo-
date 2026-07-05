/** Vue PARAMS — le poste de pilotage à deux étages (brainstorm « Paramètres », D-023).
 *
 *  GLOBAL définit · SPÉCIFIQUE hérite ou override · l'UI montre toujours lequel
 *  (pastille bleue = hérite, ambre = override, « revenir au global » en un clic).
 *  Tous les verrous sont SERVEUR : AUTORITÉ 409, réduit-seulement 422, garde-fou 428
 *  (ack explicite), lecture seule en LIVE 423 (déverrouillage explicite) — cette vue
 *  ne fait que refléter et demander, elle n'ouvre aucun chemin privilégié.
 *  Optimisé : un seul GET /settings au montage + après chaque écriture (le PUT renvoie
 *  l'état résolu) ; historique chargé à la demande ; zéro polling. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, History, Lock, LockOpen, RotateCcw, Save, ShieldAlert, Upload } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtTs } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Badge } from '@/components/ui/badge'
import { Panel } from '@/components/ui/panel'
import type { SettingHistoryEvent, SettingParam, SettingsPayload } from '@/types/schema'

const DOMAINS: { id: SettingParam['domain']; code: string; title: string; sub: string }[] = [
  { id: 'signal', code: 'A', title: 'Seuils du signal', sub: 'pondérations AUTORITÉ · seuil C3' },
  { id: 'risk', code: 'B', title: 'Risk management', sub: 'plafonds réduit-seulement — spécifique ⊆ global' },
  { id: 'alerts', code: 'C', title: 'Alertes', sub: 'anti-spam · son — consommés par le Mode Live' },
  { id: 'ai', code: 'D', title: 'Agents IA', sub: 'cadences bornées et loggées (CLAUDE §7)' },
  { id: 'live', code: 'E', title: 'Mode Live', sub: 'cycle de lecture (3 min / ralenti hors fenêtre)' },
]

const SCOPE_LABELS: Record<string, string> = {
  GLOBAL: 'GLOBAL', SVS: 'SVS', MEAN_REVERSION: 'MEAN REV',
}

const TIER_BADGE: Record<string, { label: string; cls: string }> = {
  default: { label: 'DÉFAUT', cls: 'border-term-border text-term-faint' },
  global: { label: 'HÉRITE', cls: 'border-sky-500/60 text-sky-400' },
  override: { label: 'OVERRIDE', cls: 'border-router/70 text-router' },
}

interface WriteState { key: string; scope: string } // cellule en cours d'édition

function useSettings() {
  const [data, setData] = useState<SettingsPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const refresh = useCallback(async () => {
    try { setData(await api.settings() as SettingsPayload) } catch (e) { setError((e as Error).message) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  return { data, setData, error, setError, refresh }
}

function ValueEditor({ param, scope, disabled, onCommit }: {
  param: SettingParam; scope: string; disabled: boolean
  onCommit: (value: unknown) => Promise<void>
}) {
  const scoped = param.scopes[scope]
  const [draft, setDraft] = useState<string>(String(scoped?.value ?? ''))
  useEffect(() => { setDraft(String(scoped?.value ?? '')) }, [scoped?.value])
  if (!scoped) return null

  if (param.control === 'bool') {
    const on = scoped.value === true
    return (
      <button disabled={disabled || param.locked}
        className={cn('border px-1.5 py-0.5 font-mono text-xxs font-bold uppercase disabled:opacity-40',
          on ? 'border-risk-green/60 text-risk-green' : 'border-term-border text-term-dim')}
        onClick={() => void onCommit(!on)} aria-pressed={on}>
        {on ? 'ON' : 'OFF'}
      </button>
    )
  }
  return (
    <input
      value={draft}
      disabled={disabled || param.locked}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => { if (draft !== String(scoped.value)) void onCommit(draft) }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
        if (e.key === 'Escape') setDraft(String(scoped.value))
      }}
      inputMode="decimal"
      className={cn('h-5 w-20 border border-term-border bg-term-bg px-1 text-right font-mono',
        'text-xs tabular-nums text-term-text focus:border-router focus:outline-none',
        'disabled:cursor-not-allowed disabled:opacity-50',
        param.scopes[scope].tier === 'override' && 'border-router/50')}
      aria-label={`${param.label} — ${SCOPE_LABELS[scope] ?? scope}`}
    />
  )
}

function ParamRow({ param, liveLocked, onWrite, onRevert }: {
  param: SettingParam
  liveLocked: boolean
  onWrite: (key: string, scope: string, value: unknown) => Promise<void>
  onRevert: (key: string, scope: string) => Promise<void>
}) {
  const scopes = ['GLOBAL', ...(param.scoped ? Object.keys(param.scopes).filter((s) => s !== 'GLOBAL') : [])]
  return (
    <div className="grid grid-cols-[1.5fr_2fr] items-start gap-2 border-b border-dashed border-term-grid py-1 last:border-b-0">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          {param.locked && <Lock size={10} className="shrink-0 text-term-faint" aria-hidden />}
          <span className="truncate text-xs text-term-text">{param.label}</span>
          {param.reduce_only && (
            <Badge className="border-risk-red/40 text-risk-red" title="le spécifique ne peut que réduire">⊆</Badge>
          )}
        </div>
        <p className="truncate font-mono text-xxs text-term-faint" title={param.authority}>
          {param.key} · {param.authority}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {scopes.map((scope) => {
          const cell = param.scopes[scope]
          if (!cell) return null
          const badge = TIER_BADGE[cell.tier]
          return (
            <div key={scope} className="flex items-center gap-1">
              <span className="font-mono text-xxs text-term-faint">{SCOPE_LABELS[scope] ?? scope}</span>
              <ValueEditor param={param} scope={scope} disabled={liveLocked}
                onCommit={(value) => onWrite(param.key, scope, value)} />
              {param.unit && <span className="text-xxs text-term-faint">{param.unit}</span>}
              <span className={cn('border px-1 font-mono text-xxs', badge.cls)}
                title={cell.tier === 'global' ? 'suit la valeur globale' :
                  cell.tier === 'override' ? 'valeur personnalisée — ne suit plus le global' :
                  'valeur du catalogue (config)'}>
                {badge.label}
              </span>
              {cell.tier === 'override' && !param.locked && (
                <button className="text-term-faint hover:text-term-text" disabled={liveLocked}
                  title={scope === 'GLOBAL' ? 'revenir au défaut' : 'revenir au global'}
                  onClick={() => void onRevert(param.key, scope)}>
                  <RotateCcw size={10} aria-hidden />
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function HistoryPanel() {
  const [events, setEvents] = useState<SettingHistoryEvent[] | null>(null)
  useEffect(() => {
    void (async () => {
      try { setEvents(((await api.settingsHistory()) as { history: SettingHistoryEvent[] }).history) }
      catch { setEvents([]) }
    })()
  }, [])
  return (
    <Panel code="HIST" title="Historique des changements" block="setting_events (append-only)">
      {events === null ? <p className="text-xxs text-term-faint">chargement…</p> : (
        <ul className="space-y-0.5">
          {events.length === 0 && <li className="text-xxs text-term-faint">aucun changement — tout est au défaut</li>}
          {events.slice(0, 30).map((e) => (
            <li key={e.seq} className="flex items-center justify-between gap-2 border-b border-dashed border-term-grid pb-0.5 font-mono text-xxs last:border-b-0">
              <span className="truncate text-term-dim">
                <b className={cn(e.action === 'set' ? 'text-router' : e.action === 'revert' ? 'text-sky-400' : 'text-term-text')}>
                  {e.action}
                </b>
                {' '}{e.key ?? e.name ?? ''}{e.scope && e.scope !== 'GLOBAL' ? `@${e.scope}` : ''}
                {e.action === 'set' && ` → ${JSON.stringify(e.value)}`}
              </span>
              <span className="shrink-0 text-term-faint">{e.operator ?? '—'} · {fmtTs(e.ts)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

export function ParamsView() {
  const { data, setData, error, setError, refresh } = useSettings()
  const operator = useTerminal((s) => s.operator)
  const mode = useTerminal((s) => s.session_identity?.operational_mode ?? 'PRE_SESSION')
  const [unlockLive, setUnlockLive] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [overridesOnly, setOverridesOnly] = useState(false)
  const [presetName, setPresetName] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const liveLocked = mode === 'LIVE' && !unlockLive

  const write = useCallback(async (key: string, scope: string, value: unknown,
                                   ackGuard = false): Promise<void> => {
    setError(null); setNotice(null)
    try {
      const res = await api.putSetting(key, {
        value, scope: scope === 'GLOBAL' ? null : scope, operator,
        ack_guard: ackGuard, unlock_live: unlockLive,
      }) as { settings: SettingsPayload }
      setData(res.settings)
      setNotice(`${key}${scope !== 'GLOBAL' ? `@${scope}` : ''} enregistré`)
    } catch (err) {
      const message = (err as Error).message
      // Garde-fou 428 : demande de confirmation EXPLICITE, puis ré-envoi avec ack.
      if (message.startsWith('garde-fou') && !ackGuard) {
        if (window.confirm(`${message}\n\nConfirmer quand même ?`)) return write(key, scope, value, true)
        void refresh()
        return
      }
      setError(message)
      void refresh() // resynchronise la valeur affichée sur l'état serveur
    }
  }, [operator, unlockLive, setData, setError, refresh])

  const revert = useCallback(async (key: string, scope: string) => {
    setError(null)
    try {
      const res = await api.revertSetting(key, {
        scope: scope === 'GLOBAL' ? null : scope, operator, unlock_live: unlockLive,
      }) as { settings: SettingsPayload }
      setData(res.settings)
    } catch (err) { setError((err as Error).message) }
  }, [operator, unlockLive, setData, setError])

  const exportJson = useCallback(async () => {
    const payload = await api.settingsExport()
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = 'cholismo-settings.json'; link.click()
    URL.revokeObjectURL(url)
  }, [])

  const importJson = useCallback(async (file: File) => {
    setError(null)
    try {
      const parsed = JSON.parse(await file.text()) as unknown
      await api.importSettings(parsed, unlockLive)
      await refresh()
      setNotice('import appliqué (validé serveur avant écriture)')
    } catch (err) { setError((err as Error).message) }
  }, [refresh, setError, unlockLive])

  const grouped = useMemo(() => {
    if (!data) return []
    return DOMAINS.map((d) => ({
      ...d,
      params: data.parameters.filter((p) => p.domain === d.id
        && (!overridesOnly || Object.values(p.scopes).some((s) => s.tier === 'override'))),
    })).filter((d) => d.params.length > 0)
  }, [data, overridesOnly])

  if (!data) {
    return <div className="grid flex-1 place-items-center text-xs text-term-faint">
      {error ?? 'chargement des paramètres…'}
    </div>
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-auto p-1.5">
      {/* bandeau verrou LIVE — le danger se mérite, la lecture est gratuite */}
      {mode === 'LIVE' && (
        <div className={cn('flex items-center justify-between gap-2 border px-2 py-1',
          unlockLive ? 'border-risk-red/60 bg-risk-red/5' : 'border-router/60 bg-router/5')}>
          <span className="inline-flex items-center gap-1.5 text-xxs">
            <ShieldAlert size={12} className={unlockLive ? 'text-risk-red' : 'text-router'} aria-hidden />
            <b className="uppercase">{unlockLive ? 'Déverrouillé en session LIVE' : 'Lecture seule — session LIVE en cours'}</b>
            <span className="text-term-dim">— on ne bricole pas les réglages sous le coup de l'émotion.</span>
          </span>
          <button className={cn('inline-flex items-center gap-1 border px-1.5 py-0.5 font-mono text-xxs font-bold uppercase',
            unlockLive ? 'border-risk-red text-risk-red' : 'border-term-border text-term-dim hover:text-term-text')}
            onClick={() => setUnlockLive(!unlockLive)}>
            {unlockLive ? <><Lock size={10} aria-hidden />reverrouiller</> : <><LockOpen size={10} aria-hidden />déverrouiller</>}
          </button>
        </div>
      )}

      {/* barre outils : hiérarchie, presets, export/import, diff, historique */}
      <div className="flex flex-wrap items-center gap-2 border border-term-border bg-term-panel px-2 py-1">
        <span className="font-mono text-xxs text-term-faint">
          GLOBAL définit · SPÉCIFIQUE <b className="text-sky-400">hérite</b> ou
          <b className="text-router"> override</b> · {data.overrides_count} override(s) actif(s)
        </span>
        <label className="ml-auto inline-flex items-center gap-1 text-xxs text-term-dim">
          <input type="checkbox" checked={overridesOnly} onChange={(e) => setOverridesOnly(e.target.checked)} />
          n'afficher que les déviations
        </label>
        <span className="h-4 w-px bg-term-border" />
        <input value={presetName} onChange={(e) => setPresetName(e.target.value)}
          placeholder="nom de preset…" maxLength={24}
          className="h-5 w-32 border border-term-border bg-term-bg px-1 font-mono text-xxs uppercase text-term-text placeholder:normal-case focus:border-router focus:outline-none" />
        <button className="inline-flex items-center gap-1 border border-term-border px-1.5 py-0.5 text-xxs text-term-dim hover:text-term-text disabled:opacity-40"
          disabled={!presetName.trim()}
          onClick={() => void api.savePreset(presetName).then(() => { setPresetName(''); void refresh() }).catch((e) => setError((e as Error).message))}>
          <Save size={10} aria-hidden />sauver preset
        </button>
        {data.presets.map((p) => (
          <button key={p.name}
            className="border border-term-border px-1.5 py-0.5 font-mono text-xxs text-router hover:bg-router/10 disabled:opacity-40"
            disabled={liveLocked} title={`appliquer le preset (remplace tous les overrides) — sauvé ${fmtTs(p.ts)}`}
            onClick={() => {
              if (window.confirm(`Appliquer le preset ${p.name} ? Tous les overrides actuels seront remplacés (l'historique garde tout).`))
                void api.applyPreset(p.name, unlockLive).then(() => void refresh()).catch((e) => setError((e as Error).message))
            }}>
            {p.name}
          </button>
        ))}
        <span className="h-4 w-px bg-term-border" />
        <button className="inline-flex items-center gap-1 border border-term-border px-1.5 py-0.5 text-xxs text-term-dim hover:text-term-text"
          onClick={() => void exportJson()}>
          <Download size={10} aria-hidden />export
        </button>
        <label className="inline-flex cursor-pointer items-center gap-1 border border-term-border px-1.5 py-0.5 text-xxs text-term-dim hover:text-term-text">
          <Upload size={10} aria-hidden />import
          <input type="file" accept="application/json" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void importJson(f); e.target.value = '' }} />
        </label>
        <button className={cn('inline-flex items-center gap-1 border px-1.5 py-0.5 text-xxs',
          showHistory ? 'border-router text-router' : 'border-term-border text-term-dim hover:text-term-text')}
          onClick={() => setShowHistory(!showHistory)} aria-pressed={showHistory}>
          <History size={10} aria-hidden />historique
        </button>
      </div>

      {(error || notice) && (
        <p className={cn('px-1 font-mono text-xxs', error ? 'text-risk-red' : 'text-risk-green')}>
          {error ?? notice}
        </p>
      )}

      {showHistory && <HistoryPanel />}

      <div className="grid grid-cols-1 gap-1.5 xl:grid-cols-2">
        {grouped.map((domain) => (
          <Panel key={domain.id} code={domain.code} title={domain.title} block={domain.sub}>
            {domain.params.map((param) => (
              <ParamRow key={param.key} param={param} liveLocked={liveLocked}
                onWrite={write} onRevert={revert} />
            ))}
          </Panel>
        ))}
      </div>

      <p className="text-xxs text-term-faint">
        Verrous côté serveur : AUTORITÉ → 409 · spécifique &gt; plafond global → 422 ·
        garde-fou sans ack → 428 · écriture en LIVE sans déverrouillage → 423. Chaque
        changement est un événement append-only — on édite librement, on ne perd jamais
        l'état précédent.
      </p>
    </div>
  )
}
