/** Vue JOURNAL DE BORD — archive des snapshots déterministes (D-032, /polish de D-031).
 *  Liste indexée (GET /snapshots/list) + visualiseur du contenu d'un snapshot (GET
 *  /snapshots/{id}, Markdown ou JSON). OBSERVATION seule (§2.1) : on relit des projections
 *  passées du ContextSchema écrites sur disque — jamais un ordre, jamais une valeur inventée
 *  (§3 : blocs absents restés « PAS DE DONNÉES » dans le snapshot). Liste VIRTUALISÉE (fenêtre
 *  de lignes) pour rester fluide sur des centaines de fills sans dépendance externe. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Camera, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtTs } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Panel } from '@/components/ui/panel'

// ---------- types (miroir de GET /snapshots/list et /snapshots/{id}) ----------

interface SnapItem {
  snapshot_id: string
  created_ts: number
  operator: string
  has_json: boolean
  has_md: boolean
  bytes: number
}
interface SnapListPayload { directory: string; count: number; snapshots: SnapItem[] }
interface SnapContent {
  snapshot_id: string
  json: Record<string, unknown> | null
  markdown: string | null
  json_path: string | null
  md_path: string | null
}

// Badge opérateur — couleur JAMAIS seule (§3) : toujours le texte S1·SONY / S2·YOUSSEF.
const OP_BADGE: Record<string, { label: string; cls: string }> = {
  SONY: { label: 'S1·SONY', cls: 'text-sony' },
  YOUSSEF: { label: 'S2·YOUSSEF', cls: 'text-youssef' },
}

const ROW_H = 30           // hauteur de ligne fixe (px) → base de la virtualisation
const OVERSCAN = 6         // lignes rendues au-delà de la fenêtre visible (défilement fluide)
const POLL_MS = 8000       // rafraîchissement de l'index (hors hot path)

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} o`
  return `${(n / 1024).toFixed(1)} Ko`
}

// ---------- index (liste) ----------

function useSnapshotIndex() {
  const [payload, setPayload] = useState<SnapListPayload | null>(null)
  const refresh = useCallback(async () => {
    try { setPayload(await api.snapshotsList() as SnapListPayload) } catch { /* bandeau flux couvre */ }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [refresh])
  return { payload, refresh }
}

export function JournalDeBordView() {
  const { payload, refresh } = useSnapshotIndex()
  const items = payload?.snapshots ?? []

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [content, setContent] = useState<SnapContent | null | 'loading'>(null)
  const [mode, setMode] = useState<'md' | 'json'>('md')
  const [capturing, setCapturing] = useState(false)

  // virtualisation : on ne rend que la fenêtre visible
  const listRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportH, setViewportH] = useState(480)
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight))
    ro.observe(el)
    setViewportH(el.clientHeight)
    return () => ro.disconnect()
  }, [])

  // sélection auto du plus récent à la première arrivée de la liste (consultation immédiate)
  useEffect(() => {
    if (selectedId === null && items.length > 0) setSelectedId(items[0].snapshot_id)
  }, [items, selectedId])

  // contenu du snapshot sélectionné (course annulée si la sélection change)
  useEffect(() => {
    if (!selectedId) { setContent(null); return }
    let cancelled = false
    setContent('loading')
    api.snapshot(selectedId)
      .then((c) => { if (!cancelled) setContent(c as SnapContent) })
      .catch(() => { if (!cancelled) setContent(null) })
    return () => { cancelled = true }
  }, [selectedId])

  const ensureVisible = useCallback((idx: number) => {
    const el = listRef.current
    if (!el) return
    const top = idx * ROW_H
    if (top < el.scrollTop) el.scrollTop = top
    else if (top + ROW_H > el.scrollTop + el.clientHeight) el.scrollTop = top + ROW_H - el.clientHeight
  }, [])

  const selectByIndex = useCallback((idx: number) => {
    const clamped = Math.max(0, Math.min(items.length - 1, idx))
    if (items[clamped]) { setSelectedId(items[clamped].snapshot_id); ensureVisible(clamped) }
  }, [items, ensureVisible])

  function onListKey(e: React.KeyboardEvent) {
    if (!items.length) return
    const cur = items.findIndex((x) => x.snapshot_id === selectedId)
    if (e.key === 'ArrowDown') { e.preventDefault(); selectByIndex(cur < 0 ? 0 : cur + 1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); selectByIndex(cur < 0 ? 0 : cur - 1) }
    else if (e.key === 'Home') { e.preventDefault(); selectByIndex(0) }
    else if (e.key === 'End') { e.preventDefault(); selectByIndex(items.length - 1) }
  }

  async function capture() {
    setCapturing(true)
    try {
      const res = await api.captureSnapshot() as { snapshot_id?: string }
      await refresh()
      if (res?.snapshot_id) setSelectedId(res.snapshot_id)   // montre ce qu'on vient de capturer
    } catch { /* bandeau flux couvre */ } finally { setCapturing(false) }
  }

  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const end = Math.min(items.length, Math.ceil((scrollTop + viewportH) / ROW_H) + OVERSCAN)
  const visible = items.slice(start, end)

  const headerRight = (
    <div className="flex items-center gap-1.5 text-xxs">
      <span className="tabular-nums text-term-faint">{payload ? `${payload.count} snapshot${payload.count > 1 ? 's' : ''}` : '…'}</span>
      <button onClick={capture} disabled={capturing}
        className="inline-flex items-center gap-1 border border-term-border px-1.5 py-0.5 font-semibold uppercase text-term-dim hover:text-term-text disabled:opacity-50"
        title="Capturer un snapshot de l'état courant (POST /snapshot)">
        <Camera size={10} aria-hidden /> {capturing ? '…' : 'Capturer'}
      </button>
      <button onClick={() => void refresh()}
        className="inline-flex items-center gap-1 border border-term-border px-1.5 py-0.5 font-semibold uppercase text-term-dim hover:text-term-text"
        title="Rafraîchir l'index">
        <RefreshCw size={10} aria-hidden /> Actualiser
      </button>
    </div>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col p-1.5">
      <Panel code="BORD" title="Journal de bord — snapshots" accent="none"
        block="archive · projections déterministes du schéma" right={headerRight}
        className="min-h-0 flex-1">
        <div className="grid h-full min-h-0 grid-cols-1 gap-1.5 md:grid-cols-[minmax(200px,300px)_1fr]">
          {/* ---- colonne liste (virtualisée) ---- */}
          <div className="flex min-h-0 flex-col border border-term-border">
            <div className="grid h-4 shrink-0 grid-cols-[58px_1fr_58px] items-center gap-1 border-b border-term-border bg-term-panel2 px-1 text-xxs uppercase text-term-faint">
              <span>Heure</span><span>Opérateur · id</span><span className="text-right">Taille</span>
            </div>
            {payload === null ? (
              <div className="grid flex-1 place-items-center text-xs text-term-faint">chargement…</div>
            ) : items.length === 0 ? (
              <div className="grid flex-1 place-items-center p-3 text-center text-xxs leading-relaxed text-term-faint">
                Aucun snapshot pour l'instant.<br />
                Clique <span className="text-term-dim">Capturer</span> ci-dessus, ou déclenche
                un fill NT8 (log_scraper) — chaque capture apparaît ici.
              </div>
            ) : (
              <div ref={listRef} role="listbox" aria-label="snapshots" tabIndex={0}
                onKeyDown={onListKey} onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
                className="min-h-0 flex-1 overflow-y-auto focus:outline-none focus:ring-1 focus:ring-router/40">
                <div style={{ height: items.length * ROW_H, position: 'relative' }}>
                  {visible.map((it, i) => {
                    const idx = start + i
                    const selected = it.snapshot_id === selectedId
                    const badge = OP_BADGE[it.operator] ?? { label: it.operator, cls: 'text-term-dim' }
                    return (
                      <button key={it.snapshot_id} role="option" aria-selected={selected}
                        onClick={() => setSelectedId(it.snapshot_id)}
                        style={{ position: 'absolute', top: idx * ROW_H, height: ROW_H, left: 0, right: 0 }}
                        className={cn('flex w-full flex-col justify-center gap-0 border-l-2 px-1 text-left',
                          selected ? 'border-l-router bg-term-panel2' : 'border-l-transparent hover:bg-term-panel2/50')}>
                        <div className="grid grid-cols-[58px_1fr_58px] items-center gap-1">
                          <span className="tabular-nums text-xxs text-term-text">{fmtTs(it.created_ts)}</span>
                          <span className={cn('truncate text-xxs font-bold', badge.cls)} title={it.snapshot_id}>
                            {badge.label}
                          </span>
                          <span className="text-right text-xxs tabular-nums text-term-faint">{fmtBytes(it.bytes)}</span>
                        </div>
                        <div className="flex items-center gap-1 text-xxs text-term-faint">
                          <span className="truncate font-mono" title={it.snapshot_id}>{it.snapshot_id}</span>
                          {!it.has_md && <span className="shrink-0 text-risk-yellow" title="Markdown absent">⚠ md</span>}
                          {!it.has_json && <span className="shrink-0 text-risk-yellow" title="JSON absent">⚠ json</span>}
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          {/* ---- colonne visualiseur ---- */}
          <div className="flex min-h-0 flex-col border border-term-border">
            <div className="flex h-4 shrink-0 items-center justify-between gap-2 border-b border-term-border bg-term-panel2 px-1">
              <span className="truncate font-mono text-xxs text-term-dim" title={selectedId ?? ''}>
                {selectedId ?? '—'}
              </span>
              <div className="flex shrink-0 items-center gap-0.5" role="tablist" aria-label="format">
                {(['md', 'json'] as const).map((m) => (
                  <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
                    className={cn('border px-1.5 text-xxs font-semibold uppercase',
                      mode === m ? 'border-router text-router' : 'border-term-border text-term-dim hover:text-term-text')}>
                    {m === 'md' ? 'Markdown' : 'JSON'}
                  </button>
                ))}
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {content === null ? (
                <div className="grid h-full place-items-center text-xs text-term-faint">
                  {selectedId ? 'snapshot introuvable' : 'sélectionne un snapshot'}
                </div>
              ) : content === 'loading' ? (
                <div className="grid h-full place-items-center text-xs text-term-faint">chargement…</div>
              ) : (
                <pre className="whitespace-pre-wrap break-words p-2 font-mono text-xxs leading-relaxed text-term-text">
                  {mode === 'md'
                    ? (content.markdown ?? '— pas de Markdown pour ce snapshot —')
                    : (content.json ? JSON.stringify(content.json, null, 2) : '— pas de JSON pour ce snapshot —')}
                </pre>
              )}
            </div>
          </div>
        </div>
      </Panel>
    </div>
  )
}
