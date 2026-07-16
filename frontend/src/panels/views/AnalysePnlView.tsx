/** Vue ANALYSE P&L — trades réconciliés (D-034, frontend de D-033). Consomme
 *  GET /analyses/trades (AUCUNE modif backend). Résumé global + indicateurs de santé
 *  (calculés côté client sur la liste des trades) + table chronologique des CompletedTrades.
 *  Code couleur strict VERT (R>0) / ROUGE (R<0) — JAMAIS la couleur seule (§3 : glyphe ▲/▼ +
 *  nombre signé + texte). FAIL-CLOSED : contrat inconnu → $/R affichés « — », jamais 0 inventé.
 *  VUE d'analyse (pas un panneau SSE) — cohérent §1, comme JOURNAL/RECAP.
 *
 *  Durci /devil : table VIRTUALISÉE (fenêtre de lignes → fluide à 500+ trades sans dépendance) ;
 *  garde anti-race sur les rafraîchissements ; table à défilement horizontal propre en fenêtre
 *  étroite. /polish : tuiles Total P&L / Total R / Durée moyenne CLIQUABLES → tri instantané de
 *  la table (indicateur ↓/↑ en OR sur la tuile active ; l'or = interactif, distinct du vert/
 *  rouge sémantique du signe). */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtAge, fmtInt, fmtNum, fmtSigned, fmtTs } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Panel } from '@/components/ui/panel'

// ---------- types (miroir de GET /analyses/trades) ----------

interface CompletedTrade {
  instrument: string; root: string; direction: string; quantity: number
  entry_price: number; exit_price: number; entry_ts: number; exit_ts: number
  exposure_seconds: number; pnl_points: number
  point_value: number | null; pnl_usd: number | null; r_multiple: number | null
}
interface TradesPayload {
  trades: CompletedTrade[]
  summary: {
    trade_count: number; with_usd: number; wins: number; losses: number
    total_pnl_usd: number; total_r: number; open_lots: number; unresolved_fills: number
  }
  fills_loaded: number; reference_risk_usd: number; contracts: Record<string, number>
}

type SortKey = 'chrono' | 'pnl' | 'r' | 'duration'
type SortDir = 'asc' | 'desc'

const POLL_MS = 8000
const ROW_H = 22        // hauteur de ligne fixe (px) → base de la virtualisation
const OVERSCAN = 8
const COLS = 'grid-cols-[70px_1fr_66px_40px_92px_66px_60px]'   // Heure|Instr|Sens|Qté|P&L$|R|Durée

// couleur au SIGNE — jamais seule (§3) : classe + glyphe directionnel
function signStyle(v: number | null): { cls: string; glyph: string } {
  if (v === null || v === 0 || Number.isNaN(v)) return { cls: 'text-term-dim', glyph: '·' }
  return v > 0 ? { cls: 'text-risk-green', glyph: '▲' } : { cls: 'text-risk-red', glyph: '▼' }
}

function useTrades() {
  const [data, setData] = useState<TradesPayload | null>(null)
  const reqSeq = useRef(0)   // n° de requête : seule la RÉPONSE de la dernière requête est appliquée
  const refresh = useCallback(async () => {
    const seq = ++reqSeq.current
    try {
      const d = await api.analysesTrades() as TradesPayload
      if (seq === reqSeq.current) setData(d)   // ignore les réponses périmées (race sur clics répétés)
    } catch { /* bandeau flux couvre */ }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    return () => { reqSeq.current++; window.clearInterval(timer) }   // invalide toute réponse en vol
  }, [refresh])
  return { data, refresh }
}

// tuile statique (non triable)
function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 border border-term-border bg-term-panel2 px-1.5 py-1">
      <span className="block truncate text-xxs uppercase text-term-faint">{label}</span>
      {children}
    </div>
  )
}

// tuile CLIQUABLE = contrôle de tri. Indicateur : ↕ (triable, inactif) → ↓/↑ OR (actif).
function SortTile({ label, active, dir, onClick, children }: {
  label: string; active: boolean; dir: SortDir; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
      title={`Trier la table par ${label}${active ? (dir === 'desc' ? ' (décroissant — cliquer : croissant)' : ' (croissant — cliquer : chronologique)') : ''}`}
      className={cn('min-w-0 border bg-term-panel2 px-1.5 py-1 text-left transition-colors',
        active ? 'border-router' : 'border-term-border hover:border-term-dim')}>
      <span className="flex items-center justify-between gap-1">
        <span className="truncate text-xxs uppercase text-term-faint">{label}</span>
        <span className={cn('shrink-0 text-xxs font-bold', active ? 'text-router' : 'text-term-faint/50')} aria-hidden>
          {active ? (dir === 'desc' ? '↓' : '↑') : '↕'}
        </span>
      </span>
      {children}
    </button>
  )
}

export function AnalysePnlView() {
  const { data, refresh } = useTrades()
  const [sortKey, setSortKey] = useState<SortKey>('chrono')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  // clic tuile : nouvelle clé → décroissant ; même clé : décroissant → croissant → chronologique
  const clickSort = useCallback((key: SortKey) => {
    if (sortKey !== key) { setSortKey(key); setSortDir('desc') }
    else if (sortDir === 'desc') setSortDir('asc')
    else { setSortKey('chrono'); setSortDir('desc') }
  }, [sortKey, sortDir])

  // indicateurs de santé — calculés à partir de la LISTE des trades (point 2)
  const health = useMemo(() => {
    const trades = data?.trades ?? []
    const decided = trades.filter((t) => t.pnl_usd !== null)
    const wins = decided.filter((t) => (t.pnl_usd ?? 0) > 0).length
    const losses = decided.filter((t) => (t.pnl_usd ?? 0) < 0).length
    const winRate = wins + losses > 0 ? (wins / (wins + losses)) * 100 : null
    const rs = trades.map((t) => t.r_multiple).filter((r): r is number => r !== null)
    const avgR = rs.length > 0 ? rs.reduce((a, b) => a + b, 0) / rs.length : null
    const avgDuration = trades.length > 0
      ? trades.reduce((a, t) => a + t.exposure_seconds, 0) / trades.length : null
    return { winRate, avgR, avgDuration, wins, losses }
  }, [data])

  // liste triée (mémoïsée : pas de re-tri à chaque frame de scroll). Valeurs null TOUJOURS en
  // bas — pas de valeur → pas de rang (§3), quel que soit le sens.
  const trades = useMemo(() => {
    const base = data ? [...data.trades] : []
    if (sortKey === 'chrono') return base.sort((a, b) => a.exit_ts - b.exit_ts)
    const get = sortKey === 'pnl' ? (t: CompletedTrade) => t.pnl_usd
      : sortKey === 'r' ? (t: CompletedTrade) => t.r_multiple
        : (t: CompletedTrade) => t.exposure_seconds
    const sign = sortDir === 'asc' ? 1 : -1
    return base.sort((a, b) => {
      const va = get(a), vb = get(b)
      if (va === null && vb === null) return 0
      if (va === null) return 1
      if (vb === null) return -1
      return (va - vb) * sign
    })
  }, [data, sortKey, sortDir])

  // virtualisation : ne rendre que la fenêtre visible
  const bodyRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportH, setViewportH] = useState(480)
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight))
    ro.observe(el)
    setViewportH(el.clientHeight)
    return () => ro.disconnect()
  }, [])
  // un changement de tri ramène la vue en haut de table
  useEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = 0 }, [sortKey, sortDir])

  if (data === null) {
    return <div className="grid flex-1 place-items-center text-xs text-term-faint">chargement de l'analyse…</div>
  }

  const s = data.summary
  const pnlSt = signStyle(s.total_pnl_usd)
  const rSt = signStyle(s.total_r)
  const avgSt = signStyle(health.avgR)

  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const end = Math.min(trades.length, Math.ceil((scrollTop + viewportH) / ROW_H) + OVERSCAN)
  const visible = trades.slice(start, end)

  // flèche OR sur l'en-tête de la colonne triée (renforce quelle métrique ordonne la table)
  const colArrow = (k: SortKey) => (sortKey === k ? (sortDir === 'desc' ? ' ↓' : ' ↑') : '')
  const colCls = (k: SortKey) => (sortKey === k ? 'text-router' : '')

  return (
    <div className="flex min-h-0 flex-1 flex-col p-1.5">
      <Panel code="PNL" title="Analyse P&L — trades réconciliés" accent="none"
        block="projection · /analyses/trades" className="min-h-0 flex-1"
        right={
          <div className="flex items-center gap-1.5 text-xxs">
            <span className="tabular-nums text-term-faint">
              {s.trade_count} trade{s.trade_count > 1 ? 's' : ''} · {data.fills_loaded} fills
            </span>
            <button onClick={() => void refresh()}
              className="inline-flex items-center gap-1 border border-term-border px-1.5 py-0.5 font-semibold uppercase text-term-dim hover:text-term-text"
              title="Rafraîchir l'analyse">
              <RefreshCw size={10} aria-hidden /> Actualiser
            </button>
          </div>
        }>
        <div className="flex min-h-0 flex-col gap-2">
          {/* ---- résumé global + santé (points 1 & 2). 3 tuiles cliquables = tri (/polish) ---- */}
          <div className="grid grid-cols-2 gap-1.5 md:grid-cols-4 lg:grid-cols-7">
            <SortTile label="Total P&L $" active={sortKey === 'pnl'} dir={sortDir} onClick={() => clickSort('pnl')}>
              <span className={cn('flex items-center gap-1 font-mono text-sm font-bold tabular-nums', pnlSt.cls)}>
                <span aria-hidden>{pnlSt.glyph}</span>{fmtSigned(s.total_pnl_usd, 2)}
              </span>
            </SortTile>
            <SortTile label="Total R-Multiple" active={sortKey === 'r'} dir={sortDir} onClick={() => clickSort('r')}>
              <span className={cn('flex items-center gap-1 font-mono text-sm font-bold tabular-nums', rSt.cls)}>
                <span aria-hidden>{rSt.glyph}</span>{fmtSigned(s.total_r, 2)}
              </span>
            </SortTile>
            <SortTile label="Durée moyenne" active={sortKey === 'duration'} dir={sortDir} onClick={() => clickSort('duration')}>
              <span className="font-mono text-sm font-bold tabular-nums text-term-text">
                {health.avgDuration === null ? '—' : fmtAge(health.avgDuration)}
              </span>
            </SortTile>
            <Tile label="Win Rate">
              <span className="font-mono text-sm font-bold tabular-nums text-term-text">
                {health.winRate === null ? '—' : `${fmtNum(health.winRate, 1)} %`}
              </span>
            </Tile>
            <Tile label="R moyen / trade">
              <span className={cn('flex items-center gap-1 font-mono text-sm font-bold tabular-nums', avgSt.cls)}>
                {health.avgR !== null && <span aria-hidden>{avgSt.glyph}</span>}
                {health.avgR === null ? '—' : fmtSigned(health.avgR, 2)}
              </span>
            </Tile>
            <Tile label="Lots ouverts">
              <span className={cn('font-mono text-sm font-bold tabular-nums',
                s.open_lots > 0 ? 'text-risk-yellow' : 'text-term-text')}>
                {fmtInt(s.open_lots)}{s.open_lots > 0 && ' ⚠'}
              </span>
            </Tile>
            <Tile label="Gagnants / Perdants">
              <span className="font-mono text-sm font-bold tabular-nums text-term-text">
                {health.wins} / {health.losses}
              </span>
            </Tile>
          </div>
          {s.unresolved_fills > 0 && (
            <span className="text-xxs text-risk-yellow">
              ⚠ {s.unresolved_fills} fill(s) non résolu(s) — côté/instrument manquant, exclus de l'analyse (§3)
            </span>
          )}

          {/* ---- table virtualisée (points 3 & 4) ; défilement horizontal propre en fenêtre étroite ---- */}
          <div className="flex min-h-0 flex-1 flex-col border border-term-border">
            <div ref={bodyRef} onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
              className="min-h-0 flex-1 overflow-auto">
              <div className="min-w-[560px]">
                <div className={cn('sticky top-0 z-10 grid items-center gap-1 border-b border-term-border bg-term-panel2 px-1.5 py-0.5 text-xxs uppercase text-term-faint', COLS)}>
                  <span className={colCls('chrono')}>Heure{colArrow('chrono')}</span>
                  <span>Instrument</span><span>Sens</span>
                  <span className="text-right">Qté</span>
                  <span className={cn('text-right', colCls('pnl'))}>P&L ${colArrow('pnl')}</span>
                  <span className={cn('text-right', colCls('r'))}>R{colArrow('r')}</span>
                  <span className={cn('text-right', colCls('duration'))}>Durée{colArrow('duration')}</span>
                </div>
                {trades.length === 0 ? (
                  <div className="grid place-items-center p-4 text-center text-xxs leading-relaxed text-term-faint">
                    Aucun trade réconcilié.<br />
                    Un trade apparaît une fois qu'un fill d'entrée ET de sortie ont été capturés
                    (log_scraper / snapshots).
                  </div>
                ) : (
                  <div style={{ height: trades.length * ROW_H, position: 'relative' }}>
                    {visible.map((t, i) => {
                      const idx = start + i
                      const tr = signStyle(t.r_multiple)
                      const tp = signStyle(t.pnl_usd)
                      // Sens = direction (glyphe ▲/▼ + texte), NEUTRE : vert/rouge réservé au
                      // SIGNE du P&L/R (point 4), jamais surchargé par la direction.
                      const dir = t.direction === 'LONG' ? '▲' : '▼'
                      return (
                        <div key={idx}
                          style={{ position: 'absolute', top: idx * ROW_H, left: 0, right: 0, height: ROW_H }}
                          className={cn('grid items-center gap-1 border-l-2 px-1.5 text-xxs tabular-nums', COLS,
                            tr.cls === 'text-risk-green' ? 'border-l-risk-green/50'
                              : tr.cls === 'text-risk-red' ? 'border-l-risk-red/50' : 'border-l-transparent')}>
                          <span className="text-term-dim">{fmtTs(t.entry_ts)}</span>
                          <span className="truncate font-semibold text-term-text"
                            title={`${t.instrument} · ${fmtNum(t.entry_price, 2)} → ${fmtNum(t.exit_price, 2)}`}>
                            {t.instrument}
                          </span>
                          <span className="flex items-center gap-0.5 font-semibold text-term-text">
                            <span aria-hidden>{dir}</span>{t.direction}
                          </span>
                          <span className="text-right text-term-text">{fmtInt(t.quantity)}</span>
                          <span className={cn('text-right font-semibold', tp.cls)}>
                            {t.pnl_usd === null ? '—' : fmtSigned(t.pnl_usd, 2)}
                          </span>
                          <span className={cn('flex items-center justify-end gap-0.5 font-semibold', tr.cls)}>
                            {t.r_multiple !== null && <span aria-hidden>{tr.glyph}</span>}
                            {t.r_multiple === null ? '—' : fmtSigned(t.r_multiple, 2)}
                          </span>
                          <span className="text-right text-term-dim">{fmtAge(t.exposure_seconds)}</span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
          <p className="border-t border-term-border pt-1 text-xxs text-term-faint">
            Astuce : cliquer une tuile <span className="text-router">Total P&L / Total R / Durée moyenne</span> trie
            la table (↓ décroissant · ↑ croissant · 3ᵉ clic → chronologique). R = P&L $ /
            {' '}{fmtInt(data.reference_risk_usd)} $. Contrat inconnu → $/R « — » (jamais inventés, §3).
          </p>
        </div>
      </Panel>
    </div>
  )
}
