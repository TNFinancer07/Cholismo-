/** Registre des panneaux — la table id → composant utilisée par les workspaces nommés.
 *  Chaque entrée reste UN panneau = UN bloc du schéma (CLAUDE §1) ; le registre ne fait
 *  que donner un nom stable aux panneaux existants pour que les layouts les réarrangent. */
import type { ComponentType } from 'react'
import type { PanelId } from '@/store/workspace'
import { PANEL_IDS } from '@/store/workspace'
import { CascadePanel } from '@/panels/zoneA/CascadePanel'
import { BridgewaterMatrix } from '@/panels/zoneA/BridgewaterMatrix'
import { MacroScorePanel } from '@/panels/zoneA/MacroScorePanel'
import { PipelinePanel } from '@/panels/zoneA/PipelinePanel'
import { EconCalendarPanel } from '@/panels/zoneA/EconCalendarPanel'
import { StrategiesPanel } from '@/panels/zoneB/StrategiesPanel'
import { ScenarioPanel } from '@/panels/harness/ScenarioPanel'
import { S1S2Panel } from '@/panels/zoneB/S1S2Panel'
import { OrderBookPanel } from '@/panels/zoneB/OrderBookPanel'
import { TapePanel } from '@/panels/zoneB/TapePanel'
import { AiAlertsPanel } from '@/panels/zoneB/AiAlertsPanel'
import { FootprintPanel } from '@/panels/zoneB/FootprintPanel'
import { LiquidityHeatmapPanel } from '@/panels/zoneB/LiquidityHeatmapPanel'
import { FootprintImbalancePanel } from '@/panels/zoneB/FootprintImbalancePanel'
import { CvdStratifiedPanel } from '@/panels/zoneB/CvdStratifiedPanel'
import { OptionsChainPanel } from '@/panels/zoneB/OptionsChainPanel'
import { TermStructurePanel } from '@/panels/zoneB/TermStructurePanel'
import { BridgePanel } from '@/panels/zoneB/BridgePanel'
import { SyncPanel } from '@/panels/zoneB/SyncPanel'
import { UnifiedSignalPanel } from '@/panels/zoneB/UnifiedSignalPanel'
import { Phase0DetailPanel } from '@/panels/zoneC/Phase0DetailPanel'
import { StreakPanel } from '@/panels/zoneC/StreakPanel'
import { CalibrationPanel } from '@/panels/zoneC/CalibrationPanel'
import { ModePanel } from '@/panels/modes/ModePanel'

export interface PanelDef {
  id: PanelId
  label: string
  component: ComponentType
}

export const PANEL_REGISTRY: Record<PanelId, PanelDef> = {
  A1: { id: 'A1', label: 'Cascade macro', component: CascadePanel },
  A2: { id: 'A2', label: 'Matrice Bridgewater', component: BridgewaterMatrix },
  A3: { id: 'A3', label: 'Score macro (A3)', component: MacroScorePanel },
  EC: { id: 'EC', label: 'Calendrier éco · Macro/Géo', component: EconCalendarPanel },
  S2P: { id: 'S2P', label: 'Pipeline macro Youssef', component: PipelinePanel },
  S1S: { id: 'S1S', label: 'Stratégies exécution Sony', component: StrategiesPanel },
  MOCK: { id: 'MOCK', label: 'Scénarios & pathologies', component: ScenarioPanel },
  B1: { id: 'B1', label: 'États S1 · S2', component: S1S2Panel },
  OB: { id: 'OB', label: "Carnet d'ordres ES", component: OrderBookPanel },
  TP: { id: 'TP', label: 'Tape · Time & Sales', component: TapePanel },
  IA: { id: 'IA', label: 'Alertes IA · Sweep', component: AiAlertsPanel },
  CVD: { id: 'CVD', label: 'CVD Footprint', component: FootprintPanel },
  HM: { id: 'HM', label: 'Heatmap liquidité', component: LiquidityHeatmapPanel },
  FP: { id: 'FP', label: 'Footprint · imbalances', component: FootprintImbalancePanel },
  CDS: { id: 'CDS', label: 'CVD stratifié · taille', component: CvdStratifiedPanel },
  OMON: { id: 'OMON', label: "Chaîne d'options · skew", component: OptionsChainPanel },
  VTS: { id: 'VTS', label: 'Term structure vol', component: TermStructurePanel },
  B2: { id: 'B2', label: 'Bridge variables', component: BridgePanel },
  B3: { id: 'B3', label: 'Sync S1↔S2', component: SyncPanel },
  B4: { id: 'B4', label: 'Signal unifié', component: UnifiedSignalPanel },
  C1: { id: 'C1', label: 'Phase 0 — règles', component: Phase0DetailPanel },
  C2: { id: 'C2', label: 'Streak pertes', component: StreakPanel },
  C4: { id: 'C4', label: 'Calibration', component: CalibrationPanel },
  MODE: { id: 'MODE', label: 'Vue par mode', component: ModePanel },
}

// Garde-fou : tout id canonique doit être couvert par le registre.
for (const id of PANEL_IDS) {
  if (!PANEL_REGISTRY[id]) throw new Error(`panneau non enregistré : ${id}`)
}
