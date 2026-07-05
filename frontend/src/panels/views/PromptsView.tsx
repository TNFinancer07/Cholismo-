/** Onglet « Prompts & Contextes » (Étape 9) — 6 blocs copiables, EXTRAITS RÉELS des
 *  artefacts /reference/ (voir MANIFEST.md pour le classement AUTORITÉ). Rien d'inventé :
 *  chaque bloc cite son fichier source. */
import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { useTerminal } from '@/store/terminal'

function block(title: string, body: string, authority: boolean) {
  return { title, body, authority }
}

export function PromptsView() {
  const [copied, setCopied] = useState<number | null>(null)
  const schema = useTerminal((s) => ({
    session_identity: s.session_identity, s1_state: s.s1_state, s2_state: s.s2_state,
    bridge_variables: s.bridge_variables, sync_state: s.sync_state,
    unified_signal_output: s.unified_signal_output,
  }))

  const blocks = [
    block('Sony 1 — SVS · Structural Vacuum Squeeze',
      `[reference/sony/SVS_System_Prompt_3.html — scoring v2.0 CHOP intégré]
Breakout ES/NQ par vide de liquidité (LVN) après cassure de Value Area. Fenêtre prime 09h30-11h00.
SCORE = structure×0.35 + orderflow×0.25 + macro×0.20 + sentiment×0.15 + qualité×0.05
Seuil : score ajusté ≥ 88/100 (malus session : tampon −3, zone morte −7 ; plafond 1 zone morte/semaine).
Planchers (compensation interdite) : C1 26/35 · C2 19/25 · C3 13/20 · C4 10/15 · C5 3/5.
Filtres absolus : obstacle <8 ticks · CHOP(14)15m ≥61.8 · divergence flux/absorption · news T1 ±30min · corr NQ/ES <+0.40 · VIX >30 = session suspendue.
Sizing VIX : <15→100% · 15-20→75% · 20-30→50% · >30→0. Stop-limit only (90s), BE à +1.5R, sortie CVD 2 bougies.`, true),
    block('Sony 2 — Mean Reversion · Piège d\'Absorption',
      `[reference/sony/strategie2_mean_reversion_v5_afternoon.html — v5.8 Bookmap natif]
Retournements sur niveaux institutionnels (VPOC/LVN/VAH) par excès de liquidité. Créneau 15h30-17h00.
Gates fail-fast : verrou 30min → G1 news → G2 hors VWAP ±1σ → G4 CI >61.8 (range requis) → G3 SL défini.
Seuil : ≥80/100 ; planchers : S 21/30 · O 17/25 · M 15/25 · T 10/15 (+VWAP +2/+5).
Buffer SL par CI : >90→2t · 75-90→5t · 61.8-75→3t. Taille : 80-84→25% · 85-89→50% · 90-94→75% · 95-100→100%, × mod VIX (×1/×0.75/×0.50, >30 suspendu).
Limites : 1%/trade · 2%/jour · pause 24h après 2 pertes. RMS 5 couches : KillSwitch > CircuitBreaker > StrategyOverlay > RiskSizer > PortfolioRisk.`, true),
    block('Youssef 1/3 — Fondations & quantitatif',
      `[reference/youssef/01_FONDATIONS_ET_ANALYSE_QUANTITATIVE.md]
Phase 0 quotidienne : régime kurtosis VIX — GREEN <15 · YELLOW 15-24 · ORANGE 24-35 · RED >35 ;
hystérésis 18/14 · 26/22 · 37/33 ; carry_mult 1.0/0.7/0.4/0.0 · fund 1.0/1.0/0.7/0.3 · score 1.0/0.7/0.4/0.0 ; kurtosis>9 force RED.
Étape 0 mensuelle : quadrant Bridgewater (g, π) → poids D1-D5 (table canonique fichier 1).
N1 : collecte par ÉCONOMIE (jamais par paire), triple timestamp anti look-ahead. N2A : D1 cycle · D2 monétaire (Taylor vs OIS, already-priced) · D3 inflation (Phillips vs TIPS) · D4 régime (double output score+gate) · D5 structurel (BEER).`, true),
    block('Youssef 2/3 — Qualitatif (N2B, 7 blocs)',
      `[reference/youssef/02_ANALYSE_QUALITATIVE_BLOCS.md]
B1 lecture CB 3 niveaux (l'or = contradictions entre niveaux) → B2 narratifs 5 états (réflexif : cap 7/10) →
B3 cross-market 6 corrélations (2+ cassures → re-quadrant) → B4 géopolitique (permanence 1-5) →
B5 signaux faibles 6 catégories (3+ convergents → bonus) → B6 les 10 questions (0-2 flags full · 3-4 half · 5+ NO-TRADE, veto absolu) →
B7 calibrage : ordre A→F, gates > plafonds > confiance > modulations ; déterministe, sans IA.`, true),
    block('Youssef 3/3 — N3/N4/N5 (scoring & décision)',
      `[reference/youssef/03_SCORING_ARBITRAGES_DECISION.md]
Flux 1 : poids quadrant renormalisés → raw=Σw·D → tanh → ×d4_mult → conviction=|score|×10 (cap 7 si réflexivité) → 4 horizons (long 0.5D1+0.5D5 · moyen★ 0.6D2+0.4D3 · court D4 · intra flux).
Flux 2 — 6 arbitrages : Arb1 Taylor/OIS 0.30 cap9 · Arb2 Phillips/TIPS 0.25 cap9 · Arb3 BEER z1.5 cap6 inversé jamais seul · Arb4 Carry gate AVANT seuil 2.0 cap8 · Arb5 Cycle 0.5 timing_factor cap7 · Arb6 RR 2 conditions cap6 (boucle protection carry).
N4 : Model Council · cohérence (C3 CRITICAL=STOP) · backtest WF (hit 55-65% réaliste, >70% suspect) · Brain Obsidian. Verdict : ≥6 GO plein · 4-6 réduit 30-50% · 3-4 minimal 20% · <3 NO-GO.
N5 : scénarios 60/30/10 + trade card (R:R ≥2:1).`, true),
    block('ContextSchema injecté (réel, live)', JSON.stringify(schema, null, 2), true),
  ]

  return (
    <div className="grid h-full grid-cols-3 gap-1.5 overflow-auto p-1.5">
      {blocks.map((b, i) => (
        <Panel key={b.title} code={`P${i + 1}`} title={b.title}
          block={b.authority ? 'AUTORITÉ' : 'PLACEHOLDER'}
          right={
            <div className="flex items-center gap-1">
              <Badge variant={b.authority ? 'green' : 'yellow'}>
                {b.authority ? 'AUTORITÉ' : 'PLACEHOLDER'}
              </Badge>
              <button className="text-term-dim hover:text-term-text" aria-label={`Copier ${b.title}`}
                onClick={async () => {
                  await navigator.clipboard.writeText(b.body).catch(() => undefined)
                  setCopied(i); setTimeout(() => setCopied(null), 1200)
                }}>
                {copied === i ? <Check size={11} className="text-risk-green" /> : <Copy size={11} />}
              </button>
            </div>
          }>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xxs text-term-dim">{b.body}</pre>
        </Panel>
      ))}
    </div>
  )
}
