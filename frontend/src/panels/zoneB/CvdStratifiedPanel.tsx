/** Panneau CVD GRANULAIRE stratifié par taille (D-038) — lit UN champ : `s1_state.cvd_stratified`
 *  (CLAUDE §1). Trace en HTML5 Canvas plusieurs lignes de CVD cumulé segmentées par STRATE de
 *  taille d'ordre — INSTITUTIONNEL (violet, épais : « smart money ») / RETAIL (gris, fin) / TOTAL
 *  (clair, tireté) — sur une ligne de base ZÉRO. La pente porte le sens (montée = achat net) ;
 *  la couleur de ligne encode la STRATE (jamais seule §3 : libellé + style de trait en légende).
 *  DIVERGENCE prix↔CVD institutionnel surlignée (bande + badge, VERT accumulation ⤴ / ROUGE
 *  distribution ⤵ — advisory §2.1, jamais un ordre). INTERACTIF : survol → réticule + infobulle
 *  (retail/inst/total/prix). LECTURE SEULE (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ ; vide → « PAS
 *  DE DONNÉES ». */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { CvdStratifiedValue } from '@/types/schema'

const INST = '167, 139, 250'   // violet — institutionnel (distinct : ni risque, ni opérateur, ni or)
const RETAIL = '103, 120, 143' // term-dim — retail
const TOTAL = '201, 212, 227'  // term-text — total
const GREEN = '52, 211, 153', RED = '248, 113, 113'
const PAD_L = 46, PAD_R = 8, PAD_T = 8, PAD_B = 8
const R = Math.round

function fmt(v: number): string {
  if (!Number.isFinite(v)) return '·'
  const a = Math.abs(v), s = v < 0 ? '−' : ''
  if (a >= 1e6) return s + R(a / 1e5) / 10 + 'M'
  if (a >= 1000) return s + R(a / 100) / 10 + 'k'
  return s + R(a)
}

function draw(canvas: HTMLCanvasElement, val: CvdStratifiedValue | null | undefined,
              box: { w: number; h: number }, hoverX: number | null) {
  const dpr = window.devicePixelRatio || 1
  const W = box.w, H = box.h
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
  canvas.width = R(W * dpr); canvas.height = R(H * dpr)
  const ctx = canvas.getContext('2d'); if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, W, H)
  const series = val?.series ?? []
  if (W < 4 || H < 4 || series.length === 0) return

  // étendue Y sur les 3 strates + zéro (déterministe) ; padding si plat.
  let ymin = 0, ymax = 0
  for (const p of series) for (const v of [p.retail, p.institutional, p.total]) {
    if (Number.isFinite(v)) { if (v < ymin) ymin = v; if (v > ymax) ymax = v }
  }
  if (ymax - ymin < 1e-9) { ymax += 1; ymin -= 1 }
  const n = series.length
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B
  const xOf = (i: number) => PAD_L + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW)
  const yOf = (v: number) => PAD_T + ((ymax - v) / (ymax - ymin)) * plotH

  // bande de divergence : les `bars` derniers points, teinte selon le sens (advisory §2.1).
  const div = val?.divergence ?? null
  if (div && div.bars >= 2 && n >= 2) {
    const x0 = xOf(Math.max(0, n - div.bars)), x1 = xOf(n - 1)
    ctx.fillStyle = `rgba(${div.kind === 'BULLISH' ? GREEN : RED}, 0.10)`
    ctx.fillRect(R(x0), PAD_T, R(x1 - x0), plotH)
  }

  // ligne de base ZÉRO (tiretée, repère de signe du delta)
  const y0 = R(yOf(0)) + 0.5
  ctx.strokeStyle = 'rgba(103, 120, 143, 0.5)'; ctx.lineWidth = 1
  ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(PAD_L, y0); ctx.lineTo(W - PAD_R, y0); ctx.stroke()
  ctx.setLineDash([])
  ctx.font = '9px "JetBrains Mono", ui-monospace, monospace'
  ctx.fillStyle = '#67788f'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
  ctx.fillText('0', PAD_L - 4, y0)
  ctx.fillText(fmt(ymax), PAD_L - 4, yOf(ymax) + 4)
  ctx.fillText(fmt(ymin), PAD_L - 4, yOf(ymin) - 4)

  // 3 lignes : strate encodée par COULEUR + STYLE de trait (jamais la couleur seule §3).
  const line = (key: 'retail' | 'institutional' | 'total', color: string, width: number, dash: number[]) => {
    ctx.strokeStyle = `rgb(${color})`; ctx.lineWidth = width; ctx.setLineDash(dash)
    ctx.beginPath()
    let started = false
    for (let i = 0; i < n; i++) {
      const v = series[i][key]
      if (!Number.isFinite(v)) { started = false; continue }   // trou → segment coupé (§3)
      const x = xOf(i), y = yOf(v)
      if (!started) { ctx.moveTo(x, y); started = true } else ctx.lineTo(x, y)
    }
    ctx.stroke(); ctx.setLineDash([])
  }
  line('total', TOTAL, 1, [4, 3])
  line('retail', RETAIL, 1.25, [])
  line('institutional', INST, 2, [])    // strate clé, la plus visible

  // survol : réticule + points + infobulle (interactif)
  if (hoverX != null && hoverX >= PAD_L - 6 && hoverX <= W - PAD_R + 6 && n >= 1) {
    const i = n === 1 ? 0 : Math.max(0, Math.min(n - 1, R(((hoverX - PAD_L) / plotW) * (n - 1))))
    const p = series[i], hx = R(xOf(i)) + 0.5
    ctx.strokeStyle = 'rgba(201, 212, 227, 0.35)'; ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(hx, PAD_T); ctx.lineTo(hx, H - PAD_B); ctx.stroke()
    const dot = (v: number, color: string) => {
      if (!Number.isFinite(v)) return
      ctx.fillStyle = `rgb(${color})`; ctx.beginPath(); ctx.arc(xOf(i), yOf(v), 2.2, 0, 7); ctx.fill()
    }
    dot(p.total, TOTAL); dot(p.retail, RETAIL); dot(p.institutional, INST)
    // infobulle
    const rows = [
      ['inst', fmt(p.institutional), INST], ['retail', fmt(p.retail), RETAIL],
      ['total', fmt(p.total), TOTAL], ['prix', Number.isFinite(p.price) ? String(p.price) : '·', '201, 212, 227'],
    ] as const
    ctx.font = '10px "JetBrains Mono", ui-monospace, monospace'
    const bw = 96, bh = rows.length * 13 + 6
    let bx = xOf(i) + 8; if (bx + bw > W - 2) bx = xOf(i) - 8 - bw
    const by = Math.max(2, Math.min(H - bh - 2, PAD_T))
    ctx.fillStyle = 'rgba(11, 15, 20, 0.92)'; ctx.fillRect(R(bx), R(by), bw, bh)
    ctx.strokeStyle = 'rgba(103, 120, 143, 0.6)'; ctx.strokeRect(R(bx) + 0.5, R(by) + 0.5, bw, bh)
    ctx.textBaseline = 'middle'
    rows.forEach(([label, v, color], r) => {
      const ry = by + 9 + r * 13
      ctx.textAlign = 'left'; ctx.fillStyle = `rgb(${color})`; ctx.fillText(label, bx + 6, ry)
      ctx.textAlign = 'right'; ctx.fillStyle = '#c9d4e3'; ctx.fillText(v, bx + bw - 6, ry)
    })
  }
}

export function CvdStratifiedPanel() {
  const cs = useTerminal((s) => s.s1_state?.cvd_stratified)
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [hoverX, setHoverX] = useState<number | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el); setBox({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (canvasRef.current) draw(canvasRef.current, cs?.value, box, hoverX)
  }, [cs, box, hoverX])

  const fresh = cs?.freshness
  const series = cs?.value?.series ?? []
  const noData = fresh === 'ABSENT' || series.length === 0
  const div = cs?.value?.divergence ?? null
  const threshold = cs?.value?.size_threshold ?? 10

  return (
    <Panel code="CDS" title="CVD stratifié · taille" block="s1_state.cvd_stratified" accent="sony"
      right={<span className="tabular-nums text-xxs text-term-faint">seuil ≥ {threshold} · {series.length} pts</span>}>
      <div className={cn('flex h-full min-h-0 flex-col', fresh === 'STALE' && 'opacity-60')}>
        {div && (
          <div className={cn('mb-0.5 flex shrink-0 items-center gap-1 border px-1 py-0.5 text-xxs font-bold',
            div.kind === 'BULLISH' ? 'border-risk-green/50 text-risk-green' : 'border-risk-red/50 text-risk-red')}
            title="Divergence prix ↔ CVD institutionnel (advisory, ne bloque ni ne trade — §2.1)">
            <span>{div.kind === 'BULLISH' ? '⤴ ACCUMULATION' : '⤵ DISTRIBUTION'} INST</span>
            <span className="ml-auto font-normal text-term-faint tabular-nums">
              Δprix {div.price_change > 0 ? '+' : ''}{div.price_change.toFixed(2)} · Δinst {div.inst_change > 0 ? '+' : ''}{Math.round(div.inst_change)} · {div.bars} pas
            </span>
          </div>
        )}
        <div ref={wrapRef} className="relative min-h-0 flex-1">
          <canvas ref={canvasRef} className="block"
            onMouseMove={(e) => setHoverX(e.clientX - e.currentTarget.getBoundingClientRect().left)}
            onMouseLeave={() => setHoverX(null)} />
          {noData && (
            <div className="absolute inset-0 grid place-items-center">
              <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
            </div>
          )}
          {fresh === 'STALE' && (
            <span className="absolute right-1 top-1 border border-stale/50 px-1 text-xxs font-bold text-stale">FIGÉ</span>
          )}
        </div>
        <p className="shrink-0 border-t border-term-border pt-0.5 text-xxs text-term-faint">
          <span className="text-[rgb(167,139,250)]">▬ inst</span> ·{' '}
          <span className="text-term-dim">▬ retail</span> ·{' '}
          <span className="text-term-text">┄ total</span> · montée = achat net (survol : détail)
        </p>
      </div>
    </Panel>
  )
}
